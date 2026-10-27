/* RetentionLab: the known-answer ranking. Four accounts carry predicted churn risks .8, .6, .4 and .1 and outcomes 1, 0, 1, 0.
   With capacity for two contacts the top two hold one true churner: precision .5 and recall .5. The Brier score is
   (.04 + .36 + .36 + .01) / 4 = .1925, and a high-risk selection alone says nothing about treatment effect. Every figure is
   the known-answer fixture quoted on the case study. */
scene({
  slug: "retentionlab", aspect: 1.7, seconds: 7, bg: ["#2a1630", "#1f1024"],
  init() { return {}; },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, rr }) {
    const CREAM = "#f4ecdf", CORAL = "#ef7a6a", TEAL = "#7fc8b8", MUTED = "#bfae9f", RULE = "#4a2e52";
    txt(g, "FOUR ACCOUNTS, RANKED BY PREDICTED RISK", W * 0.06, H * 0.1, { size: H * 0.03, color: CREAM, spacing: 3, weight: 600 });
    txt(g, "known-answer fixture · capacity K = 2 · outcome known after the horizon", W * 0.06, H * 0.16, { size: H * 0.022, color: MUTED });
    const rows = [[".8", 1], [".6", 0], [".4", 1], [".1", 0]];
    const lx = W * 0.06, ly = H * 0.26, rh = H * 0.1, barMax = W * 0.3;
    rows.forEach(([p, y], i) => {
      const grow = ease.out3(seg(u, 0.04 + i * 0.07, 0.2 + i * 0.07)), yy = ly + i * (rh + H * 0.03);
      const w = barMax * parseFloat(p) * grow;
      g.fillStyle = hex(CORAL, i < 2 ? 0.85 : 0.35); rr(g, lx + W * 0.1, yy, Math.max(1, w), rh * 0.6, 3); g.fill();
      txt(g, "risk " + p, lx, yy + rh * 0.45, { size: H * 0.024, color: CREAM, mono: true, alpha: grow });
      const oc = ease.out3(seg(u, 0.34, 0.44));
      txt(g, y ? "churned" : "stayed", lx + W * 0.1 + barMax + W * 0.02, yy + rh * 0.45, { size: H * 0.022, color: y ? CORAL : MUTED, mono: true, alpha: oc });
    });
    // the capacity line between rank 2 and 3
    const cap = ease.out3(seg(u, 0.3, 0.4)), cy = ly + 2 * (rh + H * 0.03) - H * 0.02;
    line(g, lx, cy, lx + W * 0.1 + barMax * cap, cy, TEAL, 1.5, [6, 4]);
    txt(g, "K = 2", lx + W * 0.1 + barMax + W * 0.02, cy + H * 0.008, { size: H * 0.02, color: TEAL, mono: true, alpha: cap });
    const rx = W * 0.62, m1 = ease.out3(seg(u, 0.48, 0.58)), m2 = ease.out3(seg(u, 0.56, 0.66)), m3 = ease.out3(seg(u, 0.66, 0.78));
    txt(g, "PRECISION@2  1 / 2 = .500000", rx, H * 0.3, { size: H * 0.024, color: CREAM, mono: true, spacing: 1, alpha: m1 });
    txt(g, "RECALL@2     1 / 2 = .500000", rx, H * 0.37, { size: H * 0.024, color: CREAM, mono: true, spacing: 1, alpha: m2 });
    txt(g, "BRIER  (.04+.36+.36+.01)/4", rx, H * 0.47, { size: H * 0.024, color: TEAL, mono: true, spacing: 1, alpha: m3 });
    txt(g, "       = .192500", rx, H * 0.53, { size: H * 0.024, color: TEAL, mono: true, spacing: 1, alpha: m3 });
    const ex = ease.out3(seg(u, 0.82, 0.94));
    if (ex > 0) {
      const bx = W * 0.62, by = H * 0.66, bbw = W * 0.32 * ex, bh = H * 0.17;
      g.fillStyle = hex(CORAL, 0.12); rr(g, bx, by, Math.max(1, bbw), bh, 4); g.fill();
      g.strokeStyle = CORAL; g.lineWidth = 1.5; rr(g, bx, by, Math.max(1, bbw), bh, 4); g.stroke();
      txt(g, "HIGH RISK IS NOT", bx + W * 0.015, by + bh * 0.33, { size: H * 0.023, color: CORAL, spacing: 1.5, mono: true, alpha: ex });
      txt(g, "TREATMENT EFFECT:", bx + W * 0.015, by + bh * 0.6, { size: H * 0.023, color: CORAL, spacing: 1.5, mono: true, alpha: ex });
      txt(g, "NO ESTIMATE WITHOUT A TRIAL", bx + W * 0.015, by + bh * 0.86, { size: H * 0.023, color: CORAL, spacing: 1.5, mono: true, alpha: ex });
    }
    line(g, W * 0.06, H * 0.93, W * 0.94, H * 0.93, RULE, 1);
  },
});
