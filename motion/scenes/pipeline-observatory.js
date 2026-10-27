/* Pipeline Observatory: the golden batch and the delivery guarantee. Ten rows arrive from a source; eight are accepted,
   one is a duplicate of an accepted key and one is quarantined (a negative quantity). Replaying the same batch leaves
   eight accepted, and a crash after the data write but before the checkpoint never makes a ninth record: the checkpoint
   stays at version 2 and the reconciliation residual stays 0.00. Every figure is the known-answer fixture quoted on the
   case study (10 received, 8 accepted, 1 duplicate, 1 quarantined; completeness 8 of 9; residual 0.00). */
scene({
  slug: "pipeline-observatory", aspect: 1.7, seconds: 7, bg: ["#161b22", "#10141a"],
  init() { return {}; },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, rr }) {
    const PALE = "#d7dde5", CYAN = "#19d3f2", CYAN_T = "#7fe3f5", AMBER = "#e8b63a", MUTED = "#8a96a6", RULE = "#2b3340";
    txt(g, "TEN ROWS · AT-LEAST-ONCE, IDEMPOTENT APPLY", W * 0.06, H * 0.1, { size: H * 0.03, color: CYAN_T, spacing: 3, weight: 600 });
    txt(g, "known-answer fixture · source src-orders · batch b-001", W * 0.06, H * 0.16, { size: H * 0.022, color: MUTED });
    // the source lane: ten rows arrive left to right
    const lx = W * 0.06, ly = H * 0.3, cell = W * 0.05, gap = cell * 0.3;
    const arrive = ease.out3(seg(u, 0.03, 0.3)), n = Math.floor(arrive * 10 + 1e-9);
    const kind = (i) => (i === 7 ? "dup" : i === 9 ? "quar" : "ok"); // the eighth row repeats a key; the tenth has a negative quantity
    for (let i = 0; i < n; i++) {
      const x = lx + i * (cell + gap), k = kind(i);
      g.fillStyle = k === "ok" ? hex(CYAN, 0.75) : k === "dup" ? hex(PALE, 0.25) : hex(AMBER, 0.85);
      rr(g, x, ly, cell, cell * 0.6, 3); g.fill();
      if (k === "dup") { g.strokeStyle = hex(PALE, 0.6); g.lineWidth = 1; g.setLineDash([3, 3]); rr(g, x, ly, cell, cell * 0.6, 3); g.stroke(); g.setLineDash([]); }
    }
    txt(g, "RECEIVED 10", lx, ly + cell * 0.6 + H * 0.05, { size: H * 0.024, color: PALE, spacing: 1.5, mono: true, alpha: ease.out3(seg(u, 0.26, 0.34)) });
    // classification: three bins
    const by = H * 0.56, bw = W * 0.26, bins = [
      ["ACCEPTED 8", CYAN, 8], ["DUPLICATE 1", PALE, 1], ["QUARANTINED 1", AMBER, 1],
    ];
    const cls = ease.out3(seg(u, 0.34, 0.5));
    bins.forEach(([label, col, count], j) => {
      const x = lx + j * (bw + W * 0.05);
      g.strokeStyle = hex(col, 0.5); g.lineWidth = 1; rr(g, x, by, bw, H * 0.11, 4); g.stroke();
      const w = Math.max(1, (bw - W * 0.02) * (count / 8) * cls);
      g.fillStyle = hex(col, j === 1 ? 0.25 : 0.7); rr(g, x + W * 0.01, by + H * 0.025, w, H * 0.06, 3); g.fill();
      txt(g, label, x + W * 0.01, by + H * 0.145, { size: H * 0.022, color: col, spacing: 1.5, mono: true, alpha: cls });
    });
    // the replay and the crash
    const rp = ease.out3(seg(u, 0.54, 0.66)), cr = ease.out3(seg(u, 0.68, 0.8));
    const ty = H * 0.76;
    txt(g, "REPLAY THE SAME 10 ROWS · ACCEPTED STAYS 8", lx, ty, { size: H * 0.026, color: PALE, spacing: 1.5, mono: true, alpha: rp });
    txt(g, "CRASH BEFORE THE CHECKPOINT · NEVER A NINTH · VERSION STAYS 2", lx, ty + H * 0.06, { size: H * 0.026, color: AMBER, spacing: 1.5, mono: true, alpha: cr });
    // completeness and the residual
    const rs = ease.out3(seg(u, 0.84, 0.94));
    txt(g, "COMPLETENESS 8 / 9 · RECONCILIATION RESIDUAL 0.00", lx, ty + H * 0.12, { size: H * 0.026, color: CYAN_T, spacing: 1.5, mono: true, alpha: rs });
    line(g, lx, H * 0.945, W * 0.94, H * 0.945, { color: RULE, width: 1 });
  },
});
