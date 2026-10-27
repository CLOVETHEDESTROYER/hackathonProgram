# EmberGuard

Live New Mexico fire hotspots from NASA's FIRMS satellites — the last two days of VIIRS and MODIS, on a map and a public GeoJSON feed — plus a pin-drop home ignition check.

**EmberGuard drops a pin on any Santa Fe home, reads free aerial imagery the way Jack Cohen reads a fire scene, and hands owners a Zone-0 punch list — what satellites can prove today, and the five ground checks that finish the job.**

Hackathon demo for Ember to Aftermath in Santa Fe. One Lambda, a public Function URL, a static map on S3, and the NASA key in SSM. No VPC, NAT, load balancer, API Gateway, or always-on compute. Imagery is public NAIP and Esri World Imagery. No paid imagery API.

## What you get

- `GET` the Function URL → GeoJSON `FeatureCollection` of hotspots in the New Mexico box.
- Open the S3 website → the same detections on a satellite map. The page draws an S3 snapshot first, then replaces it with the live feed.
- Every 15 minutes, EventBridge rebuilds `fires.geojson` on the website bucket. A successful live request writes that snapshot too.
- `GET {FunctionUrl}assess?lat=35.520712&lon=-105.937037` assesses one New Mexico property. The response is JSON with zone GeoJSON, a prioritized action list, and `engine` of `bedrock` or `heuristic`.

## Property assessment

The map takes a click or a lat/lon. The Lambda pulls a 200 m aerial chip (USGS NAIP first, Esri World Imagery if NAIP fails), an OpenStreetMap building and fence, and a USGS 3DEP slope. It draws the footprint and the 0–5 / 5–30 / 30–100 ft rings on the chip (the outer ring goes to 200 ft when the downhill grade is over about 20%).

Recommendations come from Amazon Bedrock Converse in us-west-2:

| Role | Inference profile |
| --- | --- |
| Primary | `us.anthropic.claude-sonnet-4-6` |
| If that invoke is denied, throttled, or times out | `us.amazon.nova-lite-v1:0` |
| If both fail | Greenness and ring rules already computed in the function |

`maxTokens` is 2048. The JSON always includes five `ground_required` P0 checks a nadir photo cannot close: Class A roof, ember-resistant or 1/8 inch vents, clean gutters, a 6 inch noncombustible wall base, and nothing stored under the deck. `top_p0` is the first five P0 actions. `evidence` is `aerial`, `inferred`, or `ground_required`.

This is advisory. It is not a Santa Fe County WUI assessment and not a prediction that a home will survive a fire.

If `engine` is `heuristic` and `bedrock.error` is `AccessDeniedException` mentioning a use case, an operator has to clear Anthropic access once:

1. Open [Bedrock model access](https://us-west-2.console.aws.amazon.com/bedrock/home?region=us-west-2#/modelaccess) in us-west-2.
2. Submit the one-time Anthropic use-case form for Claude Sonnet 4.6.
3. Leave the page up. Nova Lite does not need that form, and the ring rules still answer if both models are denied.

Set `BEDROCK_ENABLED=0` on the function to force the rule engine.

Query window, `west,south,east,north`: `-109.05,31.33,-103.00,37.00`.

Sensors: VIIRS NOAA-21, VIIRS NOAA-20, VIIRS S-NPP, and MODIS near real-time. Day range: 2 (the FIRMS area API allows 1–5). The bbox is fixed in the Lambda environment. Callers cannot point the key at an arbitrary area.

Each feature is a `Point` in longitude, latitude order. The collection's `ember` object lists the sensors, the query box, and when the pull was built. A warm Lambda reuses that pull for 10 minutes so a room full of refreshes does not spend the FIRMS transaction budget.

## MAP_KEY

Request a free key at <https://firms.modaps.eosdis.nasa.gov/api/map_key/>.

The stack does not create this parameter and will not overwrite it:

```bash
aws ssm put-parameter \
  --region us-west-2 \
  --name /ember-hackathon/firms-map-key \
  --description "NASA FIRMS MAP_KEY from https://firms.modaps.eosdis.nasa.gov/api/map_key/" \
  --type SecureString \
  --value "PASTE_MAP_KEY_HERE" \
  --overwrite
```

The Lambda reads that SecureString at runtime (`ssm:GetParameter` with decryption). For a local run, export `FIRMS_MAP_KEY` instead. When that variable is set, SSM is not called.

If the parameter is missing, or the value is still a placeholder such as `REPLACE_ME`, the Function URL returns HTTP 503 and does not call NASA:

```json
{
  "error": "missing_map_key",
  "message": "NASA FIRMS MAP_KEY is not set. ...",
  "parameter": "/ember-hackathon/firms-map-key",
  "docs": "https://firms.modaps.eosdis.nasa.gov/api/map_key/"
}
```

## Deploy

Account `242600734479`, region `us-west-2`, profile `default`. This account already has the CDK bootstrap stack `CDKToolkit`.

```bash
npm install
npm test
npx cdk deploy --require-approval never
```

CDK prints:

| Output | What it is |
| --- | --- |
| `FunctionUrl` | Public HTTPS GeoJSON feed |
| `MapUrl` | S3 website (HTTP) |
| `SnapshotUrl` | `fires.geojson` on that website |
| `MapKeyParameter` | `/ember-hackathon/firms-map-key` |
| `AssessExample` | Eldorado property assessment URL |

The website is plain S3 static hosting, which is HTTP. Browsers that force HTTPS will refuse it; the Function URL still returns the GeoJSON. The map loads Leaflet, Esri imagery, and (if imagery fails) OpenStreetMap from their public CDNs.

After you change the key, the next cold start or the next request on a container that has not cached a real key picks it up. Placeholder values are never cached. A container that already loaded a real key keeps it until it is recycled.

## Local feed

```bash
cd lambda/fires
FIRMS_MAP_KEY=your_key python3 firms.py > ../../web/fires.geojson
cd ../../web
python3 -m http.server 8765
```

Open `http://127.0.0.1:8765`. `web/config.js` leaves `functionUrl` empty, so the page uses the snapshot. Point `functionUrl` at the deployed Function URL to hit AWS from the local page.

The function uses the Python standard library plus `boto3`, which the Lambda runtime provides. There is nothing to pip install.

## Cost

A hackathon day of this stack stays near zero aside from the vision calls. Lambda's free tier covers the 15-minute refresh (about 96 invocations a day) plus the clicks in the room. S3 website hosting and a standard SSM SecureString are fractions of a cent. EventBridge charges about $1 per million scheduled events. Each assessment is one on-demand Converse call with a small PNG, Sonnet first and Nova Lite only if Sonnet fails. Nothing is left running. NAIP is the public USGS image service, so this path does not turn on requester-pays reads of the NAIP Open Data bucket.

## Tear down

```bash
npx cdk destroy
aws ssm delete-parameter --region us-west-2 --name /ember-hackathon/firms-map-key
```

`cdk destroy` deletes the bucket, including the snapshot, the Function URL, and the schedule. It does not delete the SSM parameter.
