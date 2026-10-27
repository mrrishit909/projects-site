/* TrustLedger: the two validity figures and the critical override. One hundred eligible customer rows: five have no e-mail
   (completeness 95 of 100), and of the ninety-five that do, ninety pass the format rule, so populated-only validity is
   90 of 95 while all-eligible validity is 90 of 100. The loop fills the row grid, marks the missing and the invalid cells,
   prints both validity figures with their labels, and then shows the one thing an average must never hide: an open
   critical key failure beside a score above 0.95. Every figure is the known-answer fixture quoted on the case study. */
scene({
  slug: "trustledger", aspect: 1.7, seconds: 7, bg: ["#f4efe4", "#ebe4d4"],
  init() { return {}; },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, rr }) {
    const INK = "#1c1c1a", FOREST = "#1f4d3a", VERMILION = "#b8432a", MUTED = "#6b6f68", RULE = "#d8d0bf";
    txt(g, "E-MAIL COMPLETENESS AND VALIDITY", W * 0.06, H * 0.11, { size: H * 0.03, color: FOREST, spacing: 3, weight: 600 });
    txt(g, "100 eligible customer rows · two denominators, both labelled", W * 0.94, H * 0.11, { size: H * 0.023, color: MUTED, align: "right" });
    const cols = 25, rows = 4, cell = W * 0.024, gap = cell * 0.35, gx = W * 0.06, gy = H * 0.22;
    const fill = ease.out3(seg(u, 0.04, 0.34)), shown = Math.floor(fill * 100);
    for (let i = 0; i < shown; i++) {
      const r = Math.floor(i / cols), c = i % cols, x = gx + c * (cell + gap), y = gy + r * (cell + gap);
      const missing = i >= 95, invalid = i >= 90 && i < 95;
      g.fillStyle = missing ? hex(INK, 0.08) : invalid ? hex(VERMILION, 0.75) : hex(FOREST, 0.8);
      rr(g, x, y, cell, cell, 2); g.fill();
      if (missing) { g.strokeStyle = hex(INK, 0.35); g.lineWidth = 1; g.setLineDash([3, 3]); rr(g, x, y, cell, cell, 2); g.stroke(); g.setLineDash([]); }
    }
    const legendY = gy + rows * (cell + gap) + H * 0.05, lg = ease.out3(seg(u, 0.3, 0.4));
    txt(g, "■ 90 VALID", gx, legendY, { size: H * 0.022, color: FOREST, spacing: 1.5, alpha: lg });
    txt(g, "■ 5 INVALID FORMAT", gx + W * 0.16, legendY, { size: H * 0.022, color: VERMILION, spacing: 1.5, alpha: lg });
    txt(g, "□ 5 MISSING", gx + W * 0.4, legendY, { size: H * 0.022, color: MUTED, spacing: 1.5, alpha: lg });
    const t1 = ease.out3(seg(u, 0.42, 0.54)), t2 = ease.out3(seg(u, 0.52, 0.64)), t3 = ease.out3(seg(u, 0.62, 0.74));
    const fy = H * 0.66;
    txt(g, "COMPLETENESS 95 / 100 = .950000", gx, fy, { size: H * 0.028, color: INK, spacing: 1.5, mono: true, alpha: t1 });
    txt(g, "VALIDITY, POPULATED ONLY 90 / 95 = .947368", gx, fy + H * 0.065, { size: H * 0.028, color: FOREST, spacing: 1.5, mono: true, alpha: t2 });
    txt(g, "VALIDITY, ALL ELIGIBLE 90 / 100 = .900000", gx, fy + H * 0.13, { size: H * 0.028, color: FOREST, spacing: 1.5, mono: true, alpha: t3 });
    const over = ease.out3(seg(u, 0.8, 0.92));
    if (over > 0) {
      const bx = W * 0.06, by = H * 0.86, bw = W * 0.88 * over, bh = H * 0.085;
      g.fillStyle = hex(VERMILION, 0.12); rr(g, bx, by, Math.max(1, bw), bh, 4); g.fill();
      g.strokeStyle = VERMILION; g.lineWidth = 1.5; rr(g, bx, by, Math.max(1, bw), bh, 4); g.stroke();
      txt(g, "WEIGHTED SCORE ABOVE .95 · OPEN CRITICAL KEY FAILURE STAYS VISIBLE", bx + W * 0.015, by + bh * 0.62, { size: H * 0.024, color: VERMILION, spacing: 1.5, alpha: over });
    }
  },
});
