# Next.js rebuild plan ("$10,000 website" tutorial applied to the portfolio)

Source: Tech With Tim, "Build $10,000 Websites using Claude Code (Ultimate Guide)", https://youtu.be/UQ9PbbPNvnc
(transcript read in full 2026-10-29). Its method: install frontend skills, brain dump + clarifying questions -> plan,
connect ImageKit + Supabase + Higgsfield via MCP, /frontend-design builds a design system with theme demos, the owner
picks one, then Next.js + Supabase backend with an admin portal, all media through ImageKit, then adaptive bitrate
streaming and a text-overlay watermark.

## Owner decisions (2026-10-29)

| Question | Answer |
|---|---|
| Backend features | Admin portal: sign in, add/edit projects, upload covers + loops through ImageKit |
| Stack | Full Next.js rewrite (as in the video) |
| Design | Generate new themes with /frontend-design, owner picks one (replaces PRECISION ATELIER) |
| Publish | Go live publicly (confirm again right before the public cut-over) |

## Architecture

- `~/projects-next/` new repo: Next.js (App Router, TypeScript).
- Supabase: `projects` table seeded from the 224 `*/project.json` files (same fields as build.py's REQUIRED plus
  note/demo/demo_label/order/cover). Row Level Security: anyone reads published rows; only the owner's auth user
  writes. Auth: email magic link, one allowlisted email. Service-role key never reaches the browser.
- ImageKit: `/portfolio/<slug>/cover.jpg`, `loop.mp4`, `loop.webm` (71 MB total). Covers via URL transforms
  (sizes, quality, `l-text` watermark "Rishit Mathur"); loops via adaptive bitrate streaming (`ik-master.m3u8`).
  Upload auth signed server-side (Next route handler with the private key).
- Pages: `/` home (catalogue), `/<slug>/` case study (same URLs as today so links keep working), `/archive`,
  `/admin` (list, edit, new, upload, publish toggle). Case pages use ISR so admin edits show without a rebuild.
- Host: Vercel (GitHub Pages cannot run a Next server). mrrishit909.github.io/projects/ then redirects there,
  per-slug, so old links resolve.
- Secrets: `.env.local`, gitignored; never pasted into commits.

## Accounts the owner must create (only they can)

1. ImageKit (free): public key, private key, URL endpoint.
2. Supabase (free): new project; connect its MCP in Claude Code (`/mcp` -> authenticate).
3. Vercel (free, sign in with GitHub) for hosting.

## Order of work

1. Theme demos (no accounts needed): 3-4 directions as one preview page; owner picks.
2. Scaffold Next.js with the chosen design system; home + case page from local JSON first.
3. Accounts connected -> seed Supabase, upload media to ImageKit, switch reads to Supabase.
4. Admin portal + auth + uploads.
5. Adaptive streaming + watermark.
6. Release gate (root CLAUDE.md): tests, Lighthouse, screenshots at 1440/768/390, read them, then deploy + redirect,
   curl every link.

## Status

- [x] Transcript read, decisions taken, plan written
- [ ] Theme demos
- [ ] Accounts
- [ ] Scaffold
- [ ] Supabase + ImageKit
- [ ] Admin portal
- [ ] Streaming + watermark
- [ ] Release gate + deploy
