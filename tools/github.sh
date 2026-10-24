#!/bin/zsh
out=~/projects-site/data/github.json
echo "[" > $out; first=1
for r in $(awk -F'\t' '$2=="false"{print $1}' $(dirname $0)/../data/repos.tsv); do
  meta=$(gh api repos/mrrishit909/$r --jq '{name:.name,description:.description,homepage:.homepage,topics:.topics,pushed_at:.pushed_at,created_at:.created_at,language:.language,stars:.stargazers_count,has_pages:.has_pages,size:.size,license:(.license.spdx_id // null)}' 2>/dev/null)
  langs=$(gh api repos/mrrishit909/$r/languages 2>/dev/null)
  readme=$(gh api repos/mrrishit909/$r/readme --jq '.content' 2>/dev/null | base64 -d 2>/dev/null | head -c 1500 | python3 -c 'import sys,json;print(json.dumps(sys.stdin.read()))')
  commits=$(gh api "repos/mrrishit909/$r/commits?per_page=1" -i 2>/dev/null | grep -i '^link:' | sed -E 's/.*page=([0-9]+)>; rel="last".*/\1/' ); [ -z "$commits" ] && commits=1
  [ $first = 1 ] || echo "," >> $out; first=0
  python3 - "$meta" "$langs" "$readme" "$commits" >> $out <<'PY'
import sys,json
m=json.loads(sys.argv[1]); m['languages']=json.loads(sys.argv[2] or '{}'); m['readme_head']=json.loads(sys.argv[3]); m['commits']=int(sys.argv[4] or 1)
print(json.dumps(m))
PY
done
echo "]" >> $out
echo DONE >> $out.log
