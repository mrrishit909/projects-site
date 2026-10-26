/* Onboard Studio: the case timeline. A case opens Friday 16:00 and completes Monday 10:00: 66 calendar hours, but only the two
   working hours (Friday 16-17, Monday 9-10) count, and one of those is a customer wait. The loop draws the calendar axis, shades
   the working intervals, lays the case bar across the weekend, then separates the one active hour from the wait. Every figure is
   the known-answer fixture quoted on the case study (66 h, 2 h, 1 h). */
scene({
  slug: "onboard-studio", aspect: 1.72, seconds: 7, bg: ["#f7f3ec", "#ede6d8"],
  init() {
    // hours since Friday 00:00 UTC; the window shown is Friday 12:00 .. Monday 12:00 (72 h)
    const working = [[9, 17], [24 * 3 + 9, 24 * 3 + 17]]; // Friday and Monday 09-17
    return { working, open: 16, done: 24 * 3 + 10, wait: [16.5, 24 * 3 + 9.5], t0: 12, t1: 24 * 3 + 12 };
  },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, rr }) {
    const INK = "#1b1d24", INDIGO = "#2b3a8f", AMBER = "#d98b1a", RULE = "#d9d2c3", MUTED = "#6b6a66";
    const x0 = W * 0.07, x1 = W * 0.93, xOf = (h) => lerp(x0, x1, (h - S.t0) / (S.t1 - S.t0));
    const axisY = H * 0.62, barY = H * 0.4, barH = H * 0.12;
    txt(g, "CASE TIMELINE", x0, H * 0.11, { size: H * 0.03, color: INDIGO, spacing: 3, weight: 600 });
    txt(g, "business hours, Mon-Fri 09:00-17:00 UTC", x1, H * 0.11, { size: H * 0.026, color: MUTED, align: "right" });
    const axis = ease.out3(seg(u, 0.02, 0.14));
    line(g, x0, axisY, lerp(x0, x1, axis), axisY, RULE, 1.5);
    [["FRI", 12], ["SAT", 36], ["SUN", 60], ["MON", 84]].forEach(([d, h]) => txt(g, d, xOf(h) + 4, axisY + H * 0.045, { size: H * 0.024, color: MUTED, spacing: 2, alpha: axis }));
    // working intervals shade in
    const sh = ease.out3(seg(u, 0.14, 0.26));
    S.working.forEach(([a, b]) => { g.fillStyle = hex(INDIGO, 0.12 * sh); g.fillRect(xOf(a), barY - H * 0.04, (xOf(b) - xOf(a)), barH + H * 0.08); });
    // the case bar grows from open to complete
    const grow = ease.inOut(seg(u, 0.28, 0.5));
    const xa = xOf(S.open), xb = lerp(xa, xOf(S.done), grow);
    g.fillStyle = hex(INK, 0.18); rr(g, xa, barY, Math.max(2, xb - xa), barH, 4); g.fill();
    txt(g, "66 H CALENDAR", (xa + xb) / 2, barY + barH + H * 0.045, { size: H * 0.026, color: INK, spacing: 1.5, align: "center", alpha: grow * (1 - 0.6 * seg(u, 0.52, 0.6)) });
    // the customer wait lays over it in amber
    const wait = ease.inOut(seg(u, 0.52, 0.66));
    const wa = xOf(S.wait[0]), wb = lerp(wa, xOf(S.wait[1]), wait);
    g.fillStyle = hex(AMBER, 0.55); rr(g, wa, barY + barH * 0.3, Math.max(1, wb - wa), barH * 0.4, 3); g.fill();
    txt(g, "CUSTOMER WAIT", (wa + wb) / 2, barY - H * 0.03, { size: H * 0.024, color: AMBER, spacing: 2, align: "center", alpha: wait });
    // the two working hours light up in indigo; one of them is active
    const lit = ease.out3(seg(u, 0.68, 0.8));
    S.working.forEach(([a, b]) => {
      const ha = Math.max(a, S.open), hb = Math.min(b, S.done); if (hb <= ha) return;
      g.fillStyle = hex(INDIGO, 0.9 * lit); rr(g, xOf(ha), barY, xOf(hb) - xOf(ha), barH, 3); g.fill();
    });
    const tally = ease.out3(seg(u, 0.8, 0.9));
    txt(g, "2 H BUSINESS", x0, H * 0.86, { size: H * 0.034, color: INDIGO, spacing: 2, mono: true, alpha: tally });
    txt(g, "1 H ACTIVE", x0 + W * 0.3, H * 0.86, { size: H * 0.034, color: INK, spacing: 2, mono: true, alpha: tally });
    txt(g, "SLA MET · 8 H ALLOWED", x1, H * 0.86, { size: H * 0.026, color: MUTED, spacing: 2, align: "right", alpha: tally });
  },
});
