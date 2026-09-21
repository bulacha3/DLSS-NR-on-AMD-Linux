/* Shared by the generated GPU kernel and the CPU ABI contract.
 * Raw Daniel LDS slots 10,11,12,13,14 map through the converted weights
 * to feature slots 6,7,10,11,14. Slot 5 remains the constant 1.
 * Preserve lmxxf's existing half RTZ and color rounding. */
DEV void lmxxf_condition_features(float *f,const lmxxf_prefix_parameters &p) {
 f[6]=Hrtz(p.values[3]); f[7]=Hrtz(p.values[1]);
 f[10]=Hrtz(p.values[2]); f[11]=Hrtz(p.values[4]); f[14]=Hrtz(p.values[5]);
}
DEV float lmxxf_condition_color(float color,const lmxxf_prefix_parameters &p) {
 return Hrtz(Hrtz(Hrtz(color)-.5f)*(p.values[0]+p.values[0]));
}
