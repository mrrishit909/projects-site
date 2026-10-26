/* Revenue Atlas: the margin bridge. A waterfall draws itself from gross sales down to contribution margin, one contract step
   at a time, then the one returned unit posts and the bridge settles to the after-return figure. Every number is the
   known-answer fixture quoted on the case study (250 -> 225 -> 85 -> 70, and 40 after the return). */
scene({
  slug: "revenue-atlas", aspect: 1.68, seconds: 7, bg: ["#f4efe6", "#e9e1d2"],
  init() {
    const steps = [
      { label: "Gross sales", v: 250, kind: "total" }, { label: "Discounts", v: -25, kind: "minus" }, { label: "Net sales", v: 225, kind: "total" },
      { label: "COGS", v: -140, kind: "minus" }, { label: "Gross profit", v: 85, kind: "total" }, { label: "Freight", v: -15, kind: "minus" },
      { label: "Contribution", v: 70, kind: "total" },
    ];
    return { steps };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, rr, fmt }) {
    const INK = "#161a22", COPPER = "#b1652c", RULE = "#c9c2b4", MUTED = "#6c6a63";
    const x0 = W * 0.07, x1 = W * 0.93, yTop = H * 0.2, yBase = H * 0.8, scale = (yBase - yTop) / 250;
    const n = S.steps.length, colW = (x1 - x0) / n, bw = colW * 0.62;
    txt(g, "MARGIN BRIDGE", x0, H * 0.1, { size: H * 0.03, color: COPPER, spacing: 3, weight: 600 });
    txt(g, "known-answer fixture, USD", x1, H * 0.1, { size: H * 0.026, color: MUTED, align: "right" });
    line(g, x0, yBase, x1, yBase, RULE, 1);
    // the return posts late in the loop: one unit back, credit 90, cost 60 reversed -> contribution 40
    const ret = ease.inOut(seg(u, 0.72, 0.86));
    let run = 0;
    S.steps.forEach((s, i) => {
      const t0 = 0.06 + i * 0.085, p = ease.out3(seg(u, t0, t0 + 0.09));
      let v = s.v;
      if (ret > 0) { if (s.label === "Net sales") v = lerp(225, 135, ret); if (s.label === "COGS") v = lerp(-140, -80, ret); if (s.label === "Gross profit") v = lerp(85, 55, ret); if (s.label === "Contribution") v = lerp(70, 40, ret); if (s.label === "Discounts") v = lerp(-25, -115, ret); }
      const x = x0 + i * colW + (colW - bw) / 2;
      let top, bot;
      if (s.kind === "total") { run = v; top = yBase - v * scale; bot = yBase; }
      else { const from = run; run = run + v; top = yBase - from * scale; bot = yBase - run * scale; }
      const h = (bot - top) * p, y = s.kind === "total" ? bot - h : top;
      g.fillStyle = s.kind === "total" ? INK : hex(COPPER, 0.9); rr(g, x, y, bw, Math.max(1, h), 3); g.fill();
      if (i > 0 && p > 0.5) line(g, x - (colW - bw), s.kind === "total" ? top : top, x, top, hex(INK, 0.35), 1);
      txt(g, (s.label === "Discounts" && ret > 0 ? "Disc. + credit" : s.label).toUpperCase(), x + bw / 2, yBase + H * 0.05, { size: H * 0.021, color: MUTED, align: "center", spacing: 1, alpha: p });
      txt(g, (v < 0 ? "−" : "") + fmt(Math.round(Math.abs(v))), x + bw / 2, Math.min(top, bot) - H * 0.02, { size: H * 0.034, color: s.kind === "total" ? INK : COPPER, align: "center", mono: true, alpha: p });
    });
    const note = seg(u, 0.74, 0.84);
    txt(g, "ONE UNIT RETURNED · CREDIT 90 · COST 60 REVERSED", x0, H * 0.94, { size: H * 0.024, color: COPPER, spacing: 2, alpha: note });
    txt(g, "ALLOCATION RESIDUAL 0.00", x1, H * 0.94, { size: H * 0.024, color: MUTED, spacing: 2, align: "right", alpha: ease.out3(seg(u, 0.6, 0.7)) });
  },
});
