/* ChangeWorks: the known-answer business case. A cost of 1,000 at period 0 and net cash inflows of 600 in periods 1 and 2 at
   a 10% annual rate give an NPV of 5000/121 = 41.32; the cumulative undiscounted flow crosses zero in period 2 (interpolated
   1.6667) and the discounted one also in period 2 (1.9167), and the two paybacks are labelled separately. The 800 capacity
   hours on the same initiative stay out of the cash flow because no conversion assumption exists. Every figure is the
   known-answer fixture quoted on the case study. */
scene({
  slug: "changeworks", aspect: 1.7, seconds: 7, bg: ["#f3ead8", "#eadfc8"],
  init() { return {}; },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, rr }) {
    const GREEN = "#17382b", BRASS = "#7d6236", BRASS_L = "#b08d57", MUTED = "#5c5a52", RULE = "#d9ccb2", RED = "#9e3b2f";
    txt(g, "THE BUSINESS CASE, PERIOD BY PERIOD", W * 0.06, H * 0.1, { size: H * 0.03, color: GREEN, spacing: 3, weight: 600 });
    txt(g, "known-answer fixture · annual periods · discount rate 10%", W * 0.06, H * 0.16, { size: H * 0.022, color: MUTED });
    // three bars: -1000, +600, +600, drawn from a zero line
    const zx = W * 0.06, zy = H * 0.5, bw = W * 0.12, gap = W * 0.06, scale = H * 0.00028;
    const flows = [[-1000, "t = 0  −1,000.00"], [600, "t = 1  +600.00"], [600, "t = 2  +600.00"]];
    line(g, zx, zy, zx + 3 * (bw + gap), zy, RULE, 1);
    flows.forEach(([v, label], i) => {
      const grow = ease.out3(seg(u, 0.04 + i * 0.1, 0.18 + i * 0.1));
      const h = Math.abs(v) * scale * grow, x = zx + i * (bw + gap);
      g.fillStyle = v < 0 ? hex(RED, 0.75) : hex(GREEN, 0.8);
      if (v < 0) rr(g, x, zy, bw, Math.max(1, h), 3); else rr(g, x, zy - h, bw, Math.max(1, h), 3);
      g.fill();
      txt(g, label, x, zy + H * 0.33, { size: H * 0.021, color: MUTED, mono: true, alpha: grow });
    });
    // discount factors and the NPV
    const rx = W * 0.62, d1 = ease.out3(seg(u, 0.36, 0.48)), d2 = ease.out3(seg(u, 0.46, 0.58)), d3 = ease.out3(seg(u, 0.56, 0.68));
    txt(g, "600 / 1.1    = 545.45", rx, H * 0.3, { size: H * 0.026, color: GREEN, mono: true, alpha: d1 });
    txt(g, "600 / 1.1²   = 495.87", rx, H * 0.37, { size: H * 0.026, color: GREEN, mono: true, alpha: d2 });
    txt(g, "NPV = 5000 / 121 = 41.32", rx, H * 0.47, { size: H * 0.03, color: BRASS, mono: true, weight: 600, alpha: d3 });
    const p1 = ease.out3(seg(u, 0.66, 0.76)), p2 = ease.out3(seg(u, 0.74, 0.84));
    txt(g, "SIMPLE PAYBACK      period 2 · 1.6667", rx, H * 0.58, { size: H * 0.023, color: GREEN, mono: true, spacing: 1, alpha: p1 });
    txt(g, "DISCOUNTED PAYBACK  period 2 · 1.9167", rx, H * 0.645, { size: H * 0.023, color: GREEN, mono: true, spacing: 1, alpha: p2 });
    const ex = ease.out3(seg(u, 0.84, 0.94));
    if (ex > 0) {
      const bx = W * 0.62, by = H * 0.73, bbw = W * 0.32 * ex, bh = H * 0.13;
      g.fillStyle = hex(BRASS_L, 0.14); rr(g, bx, by, Math.max(1, bbw), bh, 4); g.fill();
      g.strokeStyle = BRASS_L; g.lineWidth = 1.5; rr(g, bx, by, Math.max(1, bbw), bh, 4); g.stroke();
      txt(g, "800 CAPACITY HOURS", bx + W * 0.015, by + bh * 0.4, { size: H * 0.023, color: BRASS, spacing: 1.5, mono: true, alpha: ex });
      txt(g, "NOT CASH · NO CONVERSION", bx + W * 0.015, by + bh * 0.78, { size: H * 0.023, color: BRASS, spacing: 1.5, mono: true, alpha: ex });
    }
    line(g, W * 0.06, H * 0.93, W * 0.94, H * 0.93, RULE, 1);
  },
});
