# Launching Commuttr

Written 23 September 2026, while getting the app ready for the stores. Everything here is
a thing that will be asked for, or a thing that goes wrong if nobody thinks about it. The
order is the order to do it in.

## 1. Signing

`mobile/android/app/build.gradle.kts` reads `mobile/android/key.properties`, which is
gitignored along with the keystore. Without it, a release build falls back to the debug
key and logs a warning — that build runs on a phone and is refused by Play, which is the
right way round.

```bash
keytool -genkey -v -keystore commuttr-upload.jks -storetype JKS \
  -keyalg RSA -keysize 2048 -validity 10000 -alias upload
```

Put the `.jks` in `mobile/android/`, copy `key.properties.example` to `key.properties` and
fill in the two passwords. **Keep the keystore and both passwords in a password manager.**
Lose the upload key before Play App Signing is enrolled and the app can never be updated —
a new key means a new listing and every install stranded.

Enrol in Play App Signing when you first upload. Google then holds the app signing key and
your upload key becomes replaceable, which is the only safe arrangement.

## 2. What the stores must be told

The analytics added in September changed these answers. Declaring them wrongly is a
removal risk, and it is the kind of mistake that is found later rather than at review.

| Data | Collected? | Linked to an identifier? | Why |
| --- | --- | --- | --- |
| Approximate or precise location | Yes | **Yes** | A search from "use my location" or a dropped pin sends coordinates to the API, and those rows now carry the app's anonymous install id |
| App activity (search terms) | Yes | Yes | Stop and place searches are reported with the same id |
| App activity (app interactions) | Yes | Yes | Which trips and routes were searched |
| Crash logs | Yes | Yes | The app reports its own uncaught errors to the Commuttr API |
| Name, email, phone, address, contacts, photos, files | No | — | The app has no account and asks for none of it |
| Financial information | No | — | Commuttr sells no tickets and takes no payments |
| Advertising or marketing use | No | — | There are no ads and no ad SDKs |

Two answers that need care:

- **"Is data collection optional?"** Yes. Preferences → Privacy switches it off and deletes
  the id. Say so; it is a strong answer and it is true.
- **"Is data shared with third parties?"** Yes, in the sense the forms mean: aggregate
  counts may be sold or shared with operators and the City. No personal data and no
  identifiers leave. The privacy policy says this in the same words.

Apple's privacy labels use the same facts. Location and Search History under "Data Linked
to You", Crash Data under "Data Linked to You", nothing under "Data Used to Track You" —
there is no cross-app tracking here and no advertising identifier is read.

## 3. Before the first build goes up

- `COMMUTTR_ADMIN_TOKEN` set on the production API, or the dashboard is off (by design).
- The app built with `--dart-define-from-file=env/prod.json`, which points at
  `https://api.commuttr.co.za`. That host must answer over HTTPS with a valid certificate
  before the app is submitted, because every screen depends on it.
- `SUPPORT_PHONE` and `SUPPORT_CHAT_URL` are empty; the Help screen says the channel is
  not open rather than dialling nothing. Fill them or leave them, but decide.
- Confirm the launcher icon is Commuttr's, not Flutter's default.
- Run `scripts/backup.ps1` once by hand and restore it into a scratch database. A backup
  nobody has restored is a hope.

## 4. Legal, before submission

`mobile/lib/ui/views/legal/legal_content.dart` carries three markers that need a person,
not a developer:

- The Information Officer's name and address, as POPIA requires.
- The 90-day server log retention, which must match what the server actually does.
- The promise that anonymous ids are cleared after twelve months —
  `gabs_scraper.retention` now does this, and it has to be scheduled for the sentence to
  stay true.

The policy also now says aggregate counts may be sold. That sentence is what makes the
data business legal and it is the sentence a regulator would read first. Have it reviewed.

## 5. Keeping the production database fed

Nothing about the loaders is tied to this laptop except the database they open. They read
`DATABASE_URL`, so pointing them at production is one environment variable — but that
variable has to be set somewhere that runs on a schedule, and that is a decision nobody has
made yet.

**Run them on the server that holds the database, not from here.** A Golden Arrow load is
~2,900 PDFs, takes about two hours and writes roughly a million rows. Over a home
connection to a remote database that is slow and easy to interrupt half way; on the same
host as Postgres it is the same two hours with nothing in between to drop. The loaders need
Python, the `requirements.txt`, ~40 MB of PDFs on a disk that survives a redeploy
(`GABS_DATA_DIR`), and `psql`/`pg_dump` on PATH.

On a new database, apply `sql/schema.sql` once. Everything else the planner needs —
including the `trip_stop_context` view its searches read — is created by the first refresh,
because a setup step somebody has to remember is a setup step somebody forgets.

```bash
export DATABASE_URL=postgresql://user:pass@host:5432/commuttr
export COMMUTTR_API_URL=https://api.commuttr.co.za
export COMMUTTR_ADMIN_TOKEN=…        # so the load can tell the API to re-read its caches
./scripts/refresh.sh                  # all three operators
```

With `DATABASE_URL` set, `refresh.sh` and `backup.sh` use `psql` directly; without it they
fall back to the local docker container, which is what a development machine has. Same
script either way — the production path must not be a second script nobody runs.

In crontab on that host, backup first so there is always a restore point in front of a
load that rewrites the timetables:

```
0 2 *  * *  cd /srv/scrapercomm && ./scripts/backup.sh  >> data/backups/cron.log 2>&1
0 3 1,15 * *  cd /srv/scrapercomm && ./scripts/refresh.sh >> data/refresh-logs/cron.log 2>&1
```

Backups daily, timetables on the 1st and the 15th — cron has no "fortnightly", and `*/14`
on the day of the month restarts every month, so two fixed dates are the honest way to say
it. On Windows, `schtasks /sc weekly /mo 2`.

The age limits in `freshness.py` and `StatusController` are **18 days, not 14**, and that
is deliberate: a limit equal to the interval is reached in the hours before each run, so
the status page would report stale data every fortnight on schedule, for data that is about
to be replaced. An alert that cries wolf to a timetable is an alert nobody reads. 18 days
leaves room for one run to fail and be noticed.

Fortnightly is one cycle behind Golden Arrow, who reissue weekly. What makes that
acceptable rather than sloppy: the planner hides a timetable that has ended when a current
one for the same route exists, and the freshness check watches the expired share as well as
the age — so drift shows up as a number rather than as a rider being given a withdrawn bus.
If that share starts climbing, move back to weekly.

**What a run actually costs.** A load no longer re-parses a PDF whose bytes have not
changed, so the cost is set by how much Golden Arrow reissued, not by the size of the
corpus:

| | |
| --- | --- |
| a PDF that has not changed | ~0.3ms — a checksum comparison |
| a PDF that is new or reissued | **~1.2s** — parse, then write its schedules and times |
| all 2,874 unchanged (nothing to do) | 2.6s |
| all 2,874 parsed (`--reparse`) | ~2 hours |

Golden Arrow reissues 30–330 timetables in a normal week, and occasionally far more — the
week of 21 September was 1,297. So a fortnightly run is **minutes, not seconds and not
hours**: roughly 2–13 minutes typically, around half an hour after a bulk reissue. Budget
the job for an hour and do not be alarmed by five minutes.

The run exits non-zero if a step failed and 2 if everything ran but the data is still
stale, so a scheduler that reports failures reports both. Every run is also a row in
`refresh_run`, visible on the dashboard.

All three operators fetch their own data. `prasa_scraper.fetch` reads PRASA's WordPress
API (`/admin/wp-json/wp/v2/cape-town-trains`), downloads every Cape Town spreadsheet it
lists and removes the ones it no longer does, then `prasa_scraper.sheets` loads them.

Files are named from PRASA's titles rather than their published filenames, on purpose: the
public holiday sheets are published as `PPH-central-line-outbound.xlsx`, and the loader
reads the day type out of the filename as well as the sheet banner. Named as PRASA names
them, a public holiday timetable can load as a weekday one — holiday trains on a Tuesday,
which is worse than not having it at all.

Three things that make this safe to run against a live database:

- **The app stays up during a load.** Postgres readers do not see a writer's uncommitted
  work, and each loader replaces its own operator inside one transaction. This was tested
  by deleting every MyCiTi departure in an open transaction — the API kept returning MyCiTi
  journeys throughout.
- **A loader may only delete its own operator's data.** It could not always: until 23
  September a Golden Arrow load pruned every timetable not in *its* manifest, which took
  Metrorail from 16 timetables to 4. Scheduled weekly, that bug would have run weekly.
- **The backup runs first and verifies itself**, because the PDFs behind the data are
  deleted by the operators when they reissue. A lost database is not a re-run; it is gone.

## 6. Watching it once it is live

- `GET /api/status` is public and says whether each operator's data is inside its age
  limit. Point an uptime monitor at it and alert on `status != "ok"` — that catches a
  dead API *and* a loader that quietly stopped, which `/api/health` does not.
- The schedule from section 5, on the server. Check `refresh_run` has a row each fortnight.
- The operations dashboard at `/api/admin/page` shows the same, plus what riders searched
  and what they searched for and never found.
- `app_error` fills up when a build is broken. Check it after every release; a spike in
  one message is a regression with a stack trace attached.

## 7. Known gaps at launch

Written down so they are decisions rather than surprises:

- **Three journeys in 316 answer "no journey" when one exists.** Nothing times out any
  more — a sweep of 412 journeys has a slowest of 9.6s against the app's 30s limit, where
  before 14 were over it and the worst was 122s. The bound costs those three: they used to
  answer at 58s, 57s and 42s, which no rider ever saw because the app had already given up.

  The cause is worth knowing before anyone tunes it: **every slow journey returns zero
  results.** One that exists returns early; one that does not runs the two-leg query to
  exhaustion and then the heavier three-leg query. It is not search-space explosion —
  MACADAMS FACTORY to MOWBRAY has five interchange candidates, found in 48ms. The fix is a
  reachability table per operator, so "no journey" becomes an index lookup instead of a
  proof. Post-launch: the launch risk was the timeout, and that is gone.

  On a Burstable database tier everything here will be slower. Measure before choosing it.
- **Four Golden Arrow stops have no position** (ALVINCO, LEAGUES, ROUTE 2, SPEKENAM) and
  around sixty distort their own route. Journeys through them work; maps and "nearest
  stops" do not.
- **The React web app** still shows Golden Arrow cash prices and no MyCiTi fares. The
  Flutter app is correct. Either fix it or take it down before launch, because it
  contradicts the app.
- **PRASA publishes no public holiday Cape Flats outbound sheet.** The other seven exist
  and are loaded; that one has no file attached to its own listing, so there is no Cape
  Flats service from Cape Town on a public holiday in the app. It is missing at the source
  — worth asking PRASA for. (There are no Sunday trains to miss: PRASA publishes none.)
- **No journey can change between operators.** `stop_interchange` is empty and no Java
  reads it, and `ConnectionService` searches each operator separately, so bus-to-train and
  bus-to-MyCiTi journeys do not exist. A rider asking for one is told there is no way to
  get there, which is a statement about the planner and not about Cape Town. Train and bus
  stops are separate rows even at the same place — RETREAT is both, about 800m apart.
- **No second pair of hands.** One person holds the signing key, the admin token, the
  database and the support inbox. Write down where each lives.
