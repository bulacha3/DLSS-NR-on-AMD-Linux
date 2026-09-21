// Research-only full-graph smoke suite. Synthetic images, no game injection.
// Uses lmxxf's unchanged neural graph; see LICENSE.upstream.
#include "hip_reference_network.h"
#include <algorithm>
#include <array>
#include <filesystem>
#include <iostream>
#include <numeric>

using hip_reference::Network;
using hip_reference::Options;
constexpr unsigned W = 512, H = 512;

static std::vector<float> fixture(bool alternate) {
    std::vector<float> rgba(size_t(W) * H * 4);
    for (unsigned y = 0; y < H; ++y) for (unsigned x = 0; x < W; ++x) {
        size_t p = (size_t(y) * W + x) * 4;
        float r = float(x) / (W - 1), g = float(y) / (H - 1);
        rgba[p] = alternate ? 1.f - r : r;
        rgba[p + 1] = alternate ? 1.f - g : g;
        rgba[p + 2] = ((x / 32 + y / 32) & 1) ? .75f : .25f;
        rgba[p + 3] = 1.f;
    }
    return rgba;
}

static void check_output(const std::vector<float>& out) {
    if (out.size() != size_t(W) * H * 3) throw std::runtime_error("RGB output shape");
    for (float f : out) if (!std::isfinite(f) || f < 0.f || f > 1.f)
        throw std::runtime_error("nonfinite/out-of-range final RGB");
}

static void equal(const std::vector<float>& a, const std::vector<float>& b) {
    if (a.size() != b.size() || std::memcmp(a.data(), b.data(), a.size() * sizeof(float)))
        throw std::runtime_error("same-input replay was not bit-identical");
}

static void save(const std::filesystem::path& root, const std::string& name,
                 const std::vector<float>& out) {
    std::ofstream f(root / (name + ".rgb.f32"), std::ios::binary);
    if (!f.write(reinterpret_cast<const char*>(out.data()), out.size() * sizeof(float)))
        throw std::runtime_error("output write failed");
    std::ofstream ppm(root / (name + ".ppm"), std::ios::binary);
    ppm << "P6\n" << W << ' ' << H << "\n255\n";
    for (float v : out) ppm.put(static_cast<char>(std::lround(v * 255.f)));
    if (!ppm) throw std::runtime_error("preview write failed");
}

static int self_test() {
    auto a = fixture(false), b = fixture(true);
    if (a.size() != W * H * 4 || a == b || a[3] != 1 || a.back() != 1)
        throw std::runtime_error("fixture regression");
    std::vector<float> good(W * H * 3, .5f);
    check_output(good);
    equal(good, good);
    unsigned rejected = 0;
    for (float bad : {std::numeric_limits<float>::quiet_NaN(),
                      std::numeric_limits<float>::infinity(), -1.f, 2.f}) {
        auto changed = good; changed[13] = bad;
        try { check_output(changed); } catch (const std::runtime_error&) { ++rejected; }
    }
    auto changed = good; changed[123] = .25f;
    try { equal(good, changed); } catch (const std::runtime_error&) { ++rejected; }
    try { check_output({}); } catch (const std::runtime_error&) { ++rejected; }
    if (rejected != 6) throw std::runtime_error("output failure checks regressed");
    std::puts("CPU suite checks passed; GPU not initialized and network not tested.");
    return 0;
}

int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "--self-test") return self_test();
        if (argc != 4) throw std::runtime_error("Usage: network_suite ASSETS MODULES NEW_OUTPUT_DIR");
        std::filesystem::path output = argv[3];
        if (!std::filesystem::create_directory(output)) throw std::runtime_error("output directory must be new");
        auto input = fixture(false), alternate = fixture(true);
        // The upstream Infer signature checks this size even with fast_prefix.
        // fast_prefix generates noise analytically and NEVER reads this placeholder.
        const std::vector<float> unused_noise(50331648, 0.f);
        unsigned runs = 0;
        for (unsigned seed : {0u, 123u}) {
            Options o; o.assets = argv[1]; o.modules = argv[2];
            o.width = W; o.height = H; o.seed = seed; o.pooled = true; o.fast_prefix = true;
            // Keep all 71 blocks. Scalar reference path, no sparse memory/graphs,
            // production shortcuts or block skipping. This is not a FPS benchmark.
            Network network(o);
            std::set<std::string> stages;
            network.SetProgress([&](const std::string& stage) {
                stages.insert(stage);
                std::printf("stage %s\n", stage.c_str()); std::fflush(stdout);
            });
            auto run = [&](const std::string& name, const std::vector<float>& image,
                           const std::vector<float>* history = nullptr) {
                std::printf("BEGIN case=%s seed=%u history=%u\n", name.c_str(), seed, unsigned(history != nullptr));
                std::fflush(stdout); stages.clear();
                const auto start = std::chrono::steady_clock::now();
                auto result = network.Infer(image, unused_noise, history);
                check_output(result);
                for (unsigned block = 0; block <= 70; ++block)
                    if (!stages.count("block" + std::to_string(block)))
                        throw std::runtime_error("missing completed block " + std::to_string(block));
                auto bounds = std::minmax_element(result.begin(), result.end());
                const auto seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
                std::printf("COMPLETE case=%s seed=%u blocks=71 min=%.9g max=%.9g wall_seconds=%.6f\n",
                            name.c_str(), seed, *bounds.first, *bounds.second, seconds);
                network.PrintMemory(); std::fflush(stdout); ++runs;
                return result;
            };
            auto base = run("gradient", input);
            equal(base, run("replay", input));
            save(output, "seed" + std::to_string(seed), base);
            if (seed == 0) {
                auto temporal = run("history", input, &alternate);
                equal(temporal, run("history-replay", input, &alternate));
                save(output, "history", temporal);
                equal(base, run("history-reset", input));
                auto other = run("alternate", alternate);
                equal(other, run("alternate-replay", alternate));
                save(output, "alternate", other);
            }
        }
        std::printf("RESULT runs=%u blocks_per_run=71 repeats_exact=yes finite=yes external_parity=not_tested\n", runs);
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "Network suite stopped: %s\n", error.what());
        return 1;
    }
}
