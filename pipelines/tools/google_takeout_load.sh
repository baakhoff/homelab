#!/usr/bin/env bash
# Load the newest Google Takeout export into the warehouse, start to end.
#
#     pipelines/tools/google_takeout_load.sh [folder with the zips, default ~/Downloads]
#
# Run on the workstation, from anywhere in the repo, with kubectl pointing at
# the lab. It does what pipelines/google.md, "A Takeout export", does by
# hand: picks the newest export's zips (takeout-<time>-*.zip; an export in
# several parts shares the time), packs them with google_takeout_pack.py,
# copies the result into the Airflow scheduler, runs ingest_google_takeout,
# waits until it has deleted the file - which it does once every record is
# delivered - runs warehouse, and deletes the packed file here. The zips are
# kept unless you answer yes at the end.
#
# Nothing it prints is mail or history: counts, file names, progress. Made
# for Google's scheduled export ("every 2 months for 1 year"): the mail
# saying it is ready is the cue to run this.
set -euo pipefail

src="${1:-$HOME/Downloads}"
here="$(cd "$(dirname "$0")" && pwd)"
remote=/tmp/google-takeout.jsonl.gz

newest=$(ls "$src"/takeout-*.zip 2>/dev/null | sed -E 's|.*/takeout-([0-9TZ]+)-.*|\1|' | sort -u | tail -1)
if [ -z "$newest" ]; then
  echo "no takeout-*.zip in $src" >&2
  exit 1
fi
zips=("$src"/takeout-"$newest"-*.zip)
echo "export $newest: ${#zips[@]} part(s), $(du -ch "${zips[@]}" | tail -1 | cut -f1)"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
for z in "${zips[@]}"; do ln -s "$(readlink -f "$z")" "$work/"; done
packed="$work/google-takeout.jsonl.gz"
python3 "$here/google_takeout_pack.py" "$work" "$packed"

pod=$(kubectl -n airflow get pod -l component=scheduler -o jsonpath='{.items[0].metadata.name}')
airflow() { kubectl -n airflow exec "$pod" -c scheduler -- airflow "$@"; }
# yes / no for the file in the pod; anything else - the pod restarted and
# took the file with it - stops the script rather than reading as "done".
present() {
  kubectl -n airflow exec "$pod" -c scheduler -- sh -c "test -e $remote && echo yes || echo no" 2>/dev/null || echo gone
}
if [ "$(present)" = yes ]; then
  echo "$remote is already in $pod - an earlier load still running or failed. Look at ingest_google_takeout in Airflow first." >&2
  exit 1
fi
kubectl -n airflow cp "$packed" "$pod:$remote" -c scheduler
echo "copied into $pod"

airflow dags unpause ingest_google_takeout >/dev/null
airflow dags trigger ingest_google_takeout >/dev/null
echo "ingest_google_takeout started; waiting for it to finish (it deletes the file when done)"
state=yes
for _ in $(seq 1 240); do
  sleep 30
  state=$(present)
  [ "$state" = yes ] || break
  printf '.'
done
echo
case "$state" in
  no) echo "loaded" ;;
  yes) echo "not finished after 2 hours - see ingest_google_takeout in Airflow. A failed run leaves the file for its retry." >&2
       exit 1 ;;
  *) echo "the scheduler pod $pod is gone - it restarted mid-load and took the file. Run this again." >&2
     exit 1 ;;
esac

airflow dags trigger warehouse >/dev/null
echo "warehouse started - the ods tables are rebuilt in a few minutes"

read -r -p "Delete the export's zips (${zips[*]##*/})? [y/N] " answer
if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
  rm -f "${zips[@]}"
  echo "zips deleted"
else
  echo "zips kept in $src"
fi
