#ifndef LMXXF_PREFIX_PARAMETERS_H
#define LMXXF_PREFIX_PARAMETERS_H
/* Daniel 0.3.1 VarParams bytes 80..103. The first value controls RGB
 * normalization; the other five are conditioning features, not RNG gains. */
struct lmxxf_prefix_parameters { float values[6]; };
static inline int lmxxf_features_valid(const float *p) {
 if (!p || p[0] != .0625f) return 0; /* output head retains the matching 8x inverse */
 for (unsigned i=1;i<6;i++) if (!(p[i]>=-16.f && p[i]<=16.f)) return 0;
 return 1; /* ordered comparisons also reject NaN and infinity */
}
#endif
