/* ProductSignal: the experiment read. Two cohorts of one hundred mature accounts each; twenty of the control and thirty of
   the treatment activate within seven days. The loop fills the two cohort grids account by account, draws the ten-point
   difference as a bar with its 95 % interval, and shows that the interval crosses zero, so the result is not conclusive.
   Every figure is the known-answer fixture quoted on the case study (20/100 vs 30/100; +10.00 pp; interval −2.02 to
   +21.67 pp). */
scene({
  slug: "productsignal", aspect: 1.7, seconds: 7, bg: ["#faf7f2", "#f1ece3"],
  init() { return {}; },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, rr }) {
    const INK = "#1b1b24", COBALT = "#1f3fbf", VIOLET = "#6d4fc7", MUTED = "#6e6a7a", RULE = "#d9d4ca";
    txt(g, "ACTIVATION WITHIN 7 DAYS", W * 0.06, H * 0.11, { size: H * 0.03, color: COBALT, spacing: 3, weight: 600 });
    txt(g, "100 accounts per variant · account randomisation", W * 0.94, H * 0.11, { size: H * 0.024, color: MUTED, align: "right" });
    const cols = 20, rows = 5, cell = W * 0.0155, gap = cell * 0.35;
    [["CONTROL", 20, COBALT, 0.06], ["TREATMENT", 30, VIOLET, 0.52]].forEach(([name, hits, color, x0], v) => {
      const gx = W * x0, gy = H * 0.26, fill = ease.out3(seg(u, 0.05 + v * 0.18, 0.3 + v * 0.18));
      txt(g, name, gx, gy - H * 0.04, { size: H * 0.024, color: INK, spacing: 2 });
      const shown = Math.floor(fill * 100);
      for (let i = 0; i < shown; i++) {
        const r = Math.floor(i / cols), c = i % cols, x = gx + c * (cell + gap), y = gy + r * (cell + gap);
        g.fillStyle = i < hits ? color : hex(INK, 0.1); rr(g, x, y, cell, cell, 1.5); g.fill();
      }
      const label = ease.out3(seg(u, 0.32 + v * 0.18, 0.4 + v * 0.18));
      txt(g, hits + " OF 100 · " + (hits / 100).toFixed(2).replace("0.", ".") + "00", gx, gy + rows * (cell + gap) + H * 0.055, { size: H * 0.028, color: color, spacing: 1.5, mono: true, alpha: label });
    });
    const axisY = H * 0.82, x0 = W * 0.06, x1 = W * 0.94, X = (pp) => lerp(x0, x1, (pp + 5) / 30);
    const axis = ease.out3(seg(u, 0.6, 0.7));
    line(g, x0, axisY, lerp(x0, x1, axis), axisY, RULE, 1.5);
    [-5, 0, 10, 20, 25].forEach((pp) => txt(g, (pp > 0 ? "+" : "") + pp + " PP", X(pp), axisY + H * 0.045, { size: H * 0.02, color: MUTED, spacing: 1.5, align: "center", alpha: axis }));
    const zero = ease.out3(seg(u, 0.66, 0.74));
    line(g, X(0), axisY - H * 0.1 * zero, X(0), axisY, hex(INK, 0.5), 1.5);
    const ci = ease.inOut(seg(u, 0.72, 0.86));
    const lo = X(-2.02), hi = X(21.67), mid = X(10);
    if (ci > 0) line(g, lerp(mid, lo, ci), axisY - H * 0.06, lerp(mid, hi, ci), axisY - H * 0.06, VIOLET, 3);
    if (ci > 0) { g.fillStyle = VIOLET; rr(g, mid - 4, axisY - H * 0.06 - 7, 8, 14, 2); g.fill(); }
    const tally = ease.out3(seg(u, 0.84, 0.94));
    txt(g, "+10.00 PP", mid, axisY - H * 0.1, { size: H * 0.03, color: VIOLET, spacing: 2, mono: true, align: "center", alpha: tally });
    txt(g, "95 % INTERVAL −2.02 TO +21.67 · CROSSES ZERO · NOT CONCLUSIVE", x1, H * 0.95, { size: H * 0.022, color: INK, spacing: 1.5, align: "right", alpha: tally });
  },
});
