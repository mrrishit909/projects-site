/* InvoiceBridge: the three-way match. A purchase order for 10 units at 20.00, a receipt of 6, then a first invoice for 6 that
   matches 120.00 before tax and 132.00 with 10% tax; a second invoice for 4 is blocked until more is received, and the
   re-sent copy of the first is merged so one obligation remains. The loop fills the three columns in order, draws the
   match line between them, blocks the second invoice and prints the total. Every figure is the known-answer fixture
   quoted on the case study (10 x 20.00; received 6; 120.00 + 12.00 = 132.00; 4 blocked; one obligation). */
scene({
  slug: "invoicebridge", aspect: 1.7, seconds: 7, bg: ["#1c1a17", "#121110"],
  init() { return {}; },
  draw(g, u, W, H, S, { lerp, seg, ease, hex, txt, line, rr }) {
    const PAPER = "#f1e9d6", AMBER = "#e0a53a", MUTED = "#8c8679", RED = "#d8623c";
    const cols = [["PURCHASE ORDER", "10 × 20.00", 10], ["RECEIPT", "6 received", 6], ["INVOICE", "6 × 20.00", 6]];
    const cx = (i) => W * (0.2 + i * 0.3), barW = W * 0.14, baseY = H * 0.7, unitH = H * 0.038;
    txt(g, "THREE-WAY MATCH", W * 0.08, H * 0.11, { size: H * 0.03, color: AMBER, spacing: 3, weight: 600 });
    txt(g, "order · receipt · invoice", W * 0.92, H * 0.11, { size: H * 0.026, color: MUTED, align: "right" });
    cols.forEach(([name, sub, units], i) => {
      const t0 = 0.06 + i * 0.16, fill = ease.out3(seg(u, t0, t0 + 0.12));
      txt(g, name, cx(i), H * 0.22, { size: H * 0.024, color: PAPER, spacing: 2, align: "center", alpha: fill });
      txt(g, sub, cx(i), H * 0.27, { size: H * 0.024, color: MUTED, align: "center", alpha: fill });
      const h = units * unitH * fill;
      if (h > 0.5) { g.fillStyle = i === 0 ? hex(PAPER, 0.28) : AMBER; rr(g, cx(i) - barW / 2, baseY - h, barW, h, 3); g.fill(); }
      for (let k = 1; k < units; k++) { const y = baseY - k * unitH; if (y > baseY - h) line(g, cx(i) - barW / 2, y, cx(i) + barW / 2, y, hex("#121110", 0.5), 1); }
      txt(g, units + " UNITS", cx(i), baseY + H * 0.05, { size: H * 0.022, color: MUTED, spacing: 2, align: "center", alpha: fill });
    });
    const matchT = ease.inOut(seg(u, 0.5, 0.62)), yMatch = baseY - 6 * unitH;
    if (matchT > 0) line(g, cx(1) - barW / 2, yMatch, lerp(cx(1) - barW / 2, cx(2) + barW / 2, matchT), yMatch, AMBER, 2);
    txt(g, "6 = 6  MATCHED", cx(1), yMatch - H * 0.035, { size: H * 0.024, color: AMBER, spacing: 2, align: "center", alpha: matchT });
    const block = ease.out3(seg(u, 0.62, 0.74)), bh = 4 * unitH * block;
    if (bh > 0.5) { g.fillStyle = hex(RED, 0.25); rr(g, cx(2) - barW / 2, baseY - 6 * unitH - bh, barW, bh, 3); g.fill();
      g.save(); g.setLineDash([4, 4]); g.strokeStyle = RED; g.lineWidth = 1.5; rr(g, cx(2) - barW / 2, baseY - 6 * unitH - bh, barW, bh, 3); g.stroke(); g.restore(); }
    txt(g, "4 BLOCKED", cx(2) + barW / 2 + 8, baseY - 8 * unitH, { size: H * 0.022, color: RED, spacing: 2, alpha: block });
    txt(g, "nothing received", cx(2) + barW / 2 + 8, baseY - 8 * unitH + H * 0.035, { size: H * 0.02, color: MUTED, alpha: block });
    const tally = ease.out3(seg(u, 0.78, 0.9));
    txt(g, "120.00 + 12.00 TAX = 132.00", W * 0.08, H * 0.9, { size: H * 0.034, color: AMBER, spacing: 2, mono: true, alpha: tally });
    txt(g, "ONE OBLIGATION · COPY MERGED", W * 0.92, H * 0.9, { size: H * 0.024, color: PAPER, spacing: 2, align: "right", alpha: tally });
  },
});
