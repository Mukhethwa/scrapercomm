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

## 5. Watching it once it is live

- `GET /api/status` is public and says whether each operator's data is inside its age
  limit. Point an uptime monitor at it and alert on `status != "ok"` — that catches a
  dead API *and* a loader that quietly stopped, which `/api/health` does not.
- `scripts/refresh.ps1` weekly (Golden Arrow reissues weekly), `scripts/backup.ps1` daily.
- The operations dashboard at `/api/admin/page` shows the same, plus what riders searched
  and what they searched for and never found.
- `app_error` fills up when a build is broken. Check it after every release; a spike in
  one message is a regression with a stack trace attached.

## 6. Known gaps at launch

Written down so they are decisions rather than surprises:

- **City-centre journeys with a change are slow.** The query takes tens of seconds where
  the network is dense, against a 30-second timeout in the app, so a rider planning from
  the CBD can be told they are offline. This is the next engineering job.
- **Four Golden Arrow stops have no position** (ALVINCO, LEAGUES, ROUTE 2, SPEKENAM) and
  around sixty distort their own route. Journeys through them work; maps and "nearest
  stops" do not.
- **The React web app** still shows Golden Arrow cash prices and no MyCiTi fares. The
  Flutter app is correct. Either fix it or take it down before launch, because it
  contradicts the app.
- **No second pair of hands.** One person holds the signing key, the admin token, the
  database and the support inbox. Write down where each lives.
