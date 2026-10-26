# InvoiceBridge — synthetic data generator specification (P05-WORK-03)

* Seed 20261026; 12 months 2025-10-01 .. 2026-09-30; 40 vendors (3 currencies), 1,200 POs
  with 3,000 lines, receipts with partials and 2 % reversals, 2,800 invoices with lines,
  credit notes on 4 %, approval policies v1/v2 (limit change on 2026-04-01), approvals and
  rejections with separation of duties, exceptions with assignment history, export batches.
* Designed relationships: vendor group "ven-02x" invoices before receipts (quantity blocks);
  one vendor with a price-list change causing price variances from 2026-03; duplicates from
  re-sent PDFs cluster in month-ends.
* Injected defects (manifest + replay events): the same bytes under two filenames, a reused
  invoice number across vendors, partial receipts short of invoiced quantity, cumulative
  consumption, a rounding gap over tolerance, a self-approval attempt, racing approvals, a
  credit applied twice, a foreign-currency line without a rate, a correction overwriting the
  original, a repeated export after timeout, a "paid" flag attempt.
* Output under 5 MB; source bytes represented by sha256 only.
