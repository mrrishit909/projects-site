/* ServiceFlow: the queue timeline. Three tickets arrive at minute 0 and one agent serves them FIFO in ten minutes each: the
   first waits nothing, the second ten minutes, the third twenty. The loop lays the three bars on one axis, shades the waits in
   cyan and the service in cream, then prints the mean wait and the last completion. Every figure is the known-answer fixture
   quoted on the case study (waits 0, 10, 20; mean 10; completion at 30). */
scene({
  slug: "serviceflow", aspect: 1.7, seconds: 7, bg: ["#0f1b33", "#0a1224"],
  init() { return { tickets: [[0, 0, 10], [0, 10, 20], [0, 20, 30]] }; },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, rr }) {
    const CREAM = "#f3ecd9", CYAN = "#19b6d8", MUTED = "#8a93a8";
    const x0 = W * 0.16, x1 = W * 0.9, X = (m) => lerp(x0, x1, m / 32);
    txt(g, "QUEUE TIMELINE", x0, H * 0.11, { size: H * 0.03, color: CYAN, spacing: 3, weight: 600 });
    txt(g, "one agent · FIFO · 10-minute service", x1, H * 0.11, { size: H * 0.026, color: MUTED, align: "right" });
    const axis = ease.out3(seg(u, 0.02, 0.14)), axisY = H * 0.74;
    line(g, x0, axisY, lerp(x0, x1, axis), axisY, hex(CREAM, 0.3), 1.5);
    [0, 10, 20, 30].forEach((m) => txt(g, m + " MIN", X(m), axisY + H * 0.045, { size: H * 0.022, color: MUTED, spacing: 2, align: m === 0 ? "left" : "center", alpha: axis }));
    S.tickets.forEach(([arr, start, done], i) => {
      const y = H * (0.26 + i * 0.15), h = H * 0.09, t0 = 0.14 + i * 0.1;
      const arrive = ease.out3(seg(u, t0, t0 + 0.06));
      txt(g, "TICKET " + (i + 1), x0 - W * 0.02, y + h * 0.65, { size: H * 0.024, color: CREAM, spacing: 2, align: "right", alpha: arrive });
      const wait = ease.inOut(seg(u, t0 + 0.06, t0 + 0.06 + 0.12 * (start - arr) / 20 + 0.02));
      if (start > arr) { g.fillStyle = hex(CYAN, 0.35); rr(g, X(arr), y, Math.max(1, (X(start) - X(arr)) * wait), h, 3); g.fill(); }
      const serve = ease.inOut(seg(u, 0.4 + i * 0.1, 0.5 + i * 0.1));
      g.fillStyle = CREAM; rr(g, X(start), y, Math.max(1, (X(done) - X(start)) * serve), h, 3); g.fill();
      txt(g, (start - arr) + " MIN WAIT", X(done) + 8, y + h * 0.65, { size: H * 0.024, color: start > arr ? CYAN : MUTED, spacing: 1.5, alpha: serve });
    });
    const tally = ease.out3(seg(u, 0.78, 0.9));
    txt(g, "MEAN WAIT 10 MIN", x0, H * 0.9, { size: H * 0.034, color: CYAN, spacing: 2, mono: true, alpha: tally });
    txt(g, "ALL DONE AT MINUTE 30", x1, H * 0.9, { size: H * 0.026, color: CREAM, spacing: 2, align: "right", alpha: tally });
  },
});
