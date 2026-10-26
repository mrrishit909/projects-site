/* SupplyScope: the inventory trajectory. Stock on hand drifts down through March; the reorder point and target sit as
   rules on the chart; when the position (on hand + on order - backorders) falls below the reorder point the draft order
   appears: raw 60, the pack rounding lifts it to 72, and the position jumps to the target. Every figure is the known-answer
   fixture on the case study (on hand 40, on order 30, backorders 10, position 60, ROP 70, target 120, order 72). */
scene({
  slug: "supplyscope", aspect: 1.7, seconds: 7, bg: ["#eef0f2", "#dfe3e8"],
  init() {
    // units over 31 days: on hand path ending at 40; position = on hand + 30 - 10
    const onHand = [60, 60, 58, 56, 56, 53, 51, 50, 48, 46, 46, 35, 70, 68, 66, 95, 92, 88, 84, 80, 76, 72, 66, 62, 58, 54, 50, 47, 44, 42, 40];
    return { onHand, pos: onHand.map((h) => h + 30 - 10) };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, rr, path }) {
    const INK = "#15171a", ORANGE = "#f26a1b", GRAPH = "#2a2d31", RULE = "#c8ccd2", MUTED = "#5c6168";
    const x0 = W * 0.08, x1 = W * 0.82, yTop = H * 0.2, yBase = H * 0.78, scale = (yBase - yTop) / 140;
    const X = (i) => lerp(x0, x1, i / 30), Y = (v) => yBase - v * scale;
    txt(g, "INVENTORY TRAJECTORY", x0, H * 0.1, { size: H * 0.03, color: ORANGE, spacing: 3, weight: 600 });
    txt(g, "units, March, as of the 31st", W * 0.93, H * 0.1, { size: H * 0.026, color: MUTED, align: "right" });
    line(g, x0, yBase, x1, yBase, RULE, 1.5);
    // rules: reorder point 70 and target 120
    const rules = ease.out3(seg(u, 0.04, 0.16));
    [["REORDER POINT 70", 70], ["TARGET 120", 120]].forEach(([l, v]) => {
      line(g, x0, Y(v), lerp(x0, x1, rules), Y(v), hex(GRAPH, 0.35), 1);
      txt(g, l, W * 0.93, Y(v) - H * 0.015, { size: H * 0.022, color: MUTED, spacing: 2, align: "right", alpha: rules });
    });
    // the two paths draw over the month
    const draw = ease.inOut(seg(u, 0.14, 0.56));
    const ptsH = S.onHand.map((v, i) => [X(i), Y(v)]), ptsP = S.pos.map((v, i) => [X(i), Y(v)]);
    path(g, ptsP, draw, hex(GRAPH, 0.45), 2); path(g, ptsH, draw, INK, 3);
    const iEnd = Math.min(30, Math.floor(draw * 30));
    if (draw > 0) {
      txt(g, "ON HAND 40", X(30) + 6, Y(40) + H * 0.012, { size: H * 0.024, color: INK, spacing: 1.5, alpha: seg(u, 0.5, 0.58) });
      txt(g, "POSITION 60", X(30) + 6, Y(60) - H * 0.008, { size: H * 0.024, color: GRAPH, spacing: 1.5, alpha: seg(u, 0.5, 0.58) });
    }
    // below the reorder point: the order appears
    const fire = ease.back(seg(u, 0.6, 0.72));
    if (fire > 0) {
      g.fillStyle = hex(ORANGE, 0.14 * fire); g.fillRect(x0, Y(70), x1 - x0, Y(0) - Y(70));
      const bx = x0 + W * 0.02, by = yTop - H * 0.05;
      txt(g, "ORDER", bx, by + H * 0.035, { size: H * 0.024, color: ORANGE, spacing: 3, alpha: fire });
      txt(g, "120 − 60 = 60 · MOQ 50 · PACK 24 →", bx, by + H * 0.075, { size: H * 0.028, color: INK, mono: true, alpha: fire });
      txt(g, "72 UNITS", bx + W * 0.47, by + H * 0.075, { size: H * 0.034, color: ORANGE, mono: true, weight: 700, alpha: fire });
    }
    // the position jumps to the target
    const jump = ease.out3(seg(u, 0.74, 0.86));
    if (jump > 0) { line(g, X(30), Y(60), X(30), lerp(Y(60), Y(132), jump), ORANGE, 3); txt(g, "132", X(30) - 10, Y(132) - H * 0.015, { size: H * 0.026, color: ORANGE, mono: true, align: "right", alpha: jump }); }
    txt(g, "RECEIPTS, THEN DEMAND, THEN REVIEW", x0, H * 0.93, { size: H * 0.022, color: MUTED, spacing: 2, alpha: ease.out3(seg(u, 0.2, 0.3)) });
    txt(g, "NOTHING IS EVER ORDERED", W * 0.93, H * 0.93, { size: H * 0.022, color: MUTED, spacing: 2, align: "right", alpha: ease.out3(seg(u, 0.8, 0.9)) });
  },
});
