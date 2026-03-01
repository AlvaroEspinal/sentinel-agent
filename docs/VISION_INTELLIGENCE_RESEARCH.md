# Vision Intelligence Research: Facial Recognition, LPR, Cameras, Satellite Imagery

**Date**: 2026-02-27
**Purpose**: Research findings for upgrading Sentinel Agent with computer vision capabilities

---

## 1. Facial Recognition -- Open Source Tools & Databases

### Production-Grade Libraries

| Library | GitHub | Strength |
|---------|--------|----------|
| **InsightFace** | deepinsight/insightface | State-of-the-art accuracy (ArcFace); sub-2ms GPU inference; ONNX optimized |
| **DeepFace** | serengil/deepface | Unified wrapper for 8+ backends; easiest to start |
| **CompreFace** | exadel-inc/CompreFace | Full Docker system: REST API, PostgreSQL, horizontal scaling, face/age/gender/mask detection |
| **face_recognition** | ageitgey/face_recognition | Simplest API; built on dlib; good for prototyping |

### Pre-Trained Models

| Model | LFW Accuracy | Embedding Size | Best For |
|-------|-------------|----------------|----------|
| **ArcFace** (InsightFace) | 99.80%+ | 512 | General-purpose, best accuracy-to-speed |
| **AdaFace** | 99.82% | 512 | Low-quality / degraded imagery (adaptive margin) |
| **FaceNet512** | 99.65% | 512 | Well-documented, good baseline |
| **VGG-Face** | 98.95% | 2048 | Rich training data (VGGFace2) |
| **SFace** | 99.60% | 128 | Lightweight deployment |

### Training Datasets

| Dataset | Size | Identities | Notes |
|---------|------|-----------|-------|
| **WebFace260M** | 260M images | 4M | Largest public face dataset |
| **MS1M-ArcFace** | ~10M images | 100K | Cleaned MS-Celeb-1M; widely used |
| **VGGFace2** | 3.31M images | 9,131 | Wide pose/age/lighting variation |
| **QMUL-SurvFace** | 463K images | 15,573 | Surveillance-specific low-resolution |
| **CASIA-WebFace** | 500K images | 10,575 | Clean, smaller, good for initial training |
| **CelebA** | 202K images | 10,177 | Rich attribute annotations |

### Low-Quality CCTV Enhancement Pipeline

1. **Super-Resolution**: GFPGAN (TencentARC/GFPGAN) or CodeFormer (sczhou/CodeFormer) for face-specific restoration
2. **Recognition**: AdaFace (adaptive margin for degraded imagery) or ArcFace ResNet-100
3. **Fallback**: Person Re-Identification (ReID) via FastReID -- gait, clothing, body shape when face insufficient

### Performance Benchmarks

| System | Hardware | Speed |
|--------|----------|-------|
| InsightFace (ArcFace) | GPU | Sub-2ms per face |
| InsightFace (ArcFace) | CPU | ~50-100ms per face |
| face_recognition (dlib CNN) | CPU | ~3-5 FPS at 720p |
| CompreFace | GPU cluster | Horizontally scalable |

### Complete Open-Source Systems

| System | Capabilities |
|--------|-------------|
| **Frigate NVR** (blakeblackshear/frigate) | Object detection + face recognition + LPR (v0.16+); Google Coral TPU; Home Assistant |
| **SharpAI DeepCamera** (SharpAI/DeepCamera) | Face (MTCNN+ArcFace) + Person ReID (YOLOv7+FastReID) + car detection; Milvus vector DB |
| **CompreFace** | Microservices: nginx -> API -> Embedding servers -> PostgreSQL; Kubernetes-ready |
| **Viseron** (roflcoopter/viseron) | NVR with object detection, face recognition, LPR |

---

## 2. License Plate Recognition (LPR/ALPR)

### Open-Source Tools

| Tool | Key Features |
|------|-------------|
| **FastALPR** (ankandrew/fast-alpr) | ONNX-optimized; YOLO-v9-t detection + CCT OCR; PyPI package |
| **OpenALPR** (openalpr/openalpr) | Original ALPR; now commercial (Rekor); AGPL open core |
| **Frigate NVR v0.16+** | Integrated LPR alongside face recognition and object tracking |
| **V0LT Predator** (connervieira/Predator) | Built on OpenALPR; dashcam recording + real-time analysis |

### How Flock Safety Works

1. Solar-powered cameras, motion-activated, captures rear of vehicles
2. On-device ML: plate text + "Vehicle Fingerprint" (make/model/color/damage/accessories)
3. LTE to AWS Cloud, end-to-end encrypted, 30-day retention
4. Real-time comparison against NCIC + state stolen vehicle databases + local BOLOs
5. Alert to officers on match; officer MUST verify before enforcement action
6. Key differentiator: identifies vehicles even without readable plate via visual characteristics

### Plate Lookup Databases

**Law Enforcement Only:**
- NCIC (National Crime Information Center): stolen vehicles/plates, wanted persons, missing persons
- State DMV databases: vehicle registration, owner info
- NLETS: interstate information sharing

**Commercial APIs:**
- **DRN Data** (Motorola Solutions): billions of plate scans from repo drivers; $20/search
- **Plate Recognizer**: plate -> make/model/color; $75/mo for 50K lookups; on-premise SDK
- **PlateToVin**: plate + state -> VIN
- **VehicleRegistrationAPI**: registration status, all 50 US states

**Important**: Direct plate-to-OWNER lookups require law enforcement credentials or DPPA-compliant purpose. Commercial APIs return vehicle info but NOT registered owner PII.

### LPR Training Datasets

| Dataset | Size | Region |
|---------|------|--------|
| **CCPD** | 290K images | China (MIT license) |
| **UFPR-ALPR** | 4,500 images | Brazil |
| **UC3M-LP** | 12,757 chars | Europe/Spain |
| **OpenImages plate subset** | Large | Mixed |

Note: No single large open-source US plate dataset exists. Production US systems use proprietary data + synthetic plate generators.

---

## 3. How Verification & Identification Systems Work

### Facial Recognition Pipeline (Camera to Match)

```
Camera Feed (RTSP/ONVIF)
  -> Frame Extraction (OpenCV)
  -> Face Detection (SCRFD/RetinaFace)
  -> Face Alignment (5-point landmarks, affine transform)
  -> Quality Assessment (blur, occlusion, pose, illumination)
  -> Super-Resolution if needed (GFPGAN/CodeFormer)
  -> Feature Extraction (ArcFace -> 512-dim vector)
  -> Database Search (FAISS/Milvus ANN, cosine similarity)
  -> Confidence Thresholding (0.6-0.7 investigative, 0.85+ automated)
  -> Human Review (mandatory for enforcement)
```

### Confidence Scoring

- Top 100 algorithms: >99.5% accurate across demographics (NIST FRVT 2024)
- At 99% threshold: 35% miss rate. At no threshold: 4.7% miss rate on "wild" photos
- Demographic bias: error rates higher for women and Black individuals
- All 10 publicized US false arrests from facial recognition involved Black individuals (except 1)

### Law Enforcement Databases

- **FBI NGI** (Next Generation Identification): 30M+ criminal mugshots, 99.6% fingerprint accuracy
- **Clearview AI**: 70B+ images scraped from public web, faceprint indexing without consent
- **ALPR Hot Lists**: NCIC stolen vehicles/plates + state BOLOs, updated daily minimum

### Legal Framework

| Law | Jurisdiction | Key Rule |
|-----|-------------|----------|
| **BIPA** | Illinois | Written consent required; $1,000-$5,000 per violation |
| **CCPA/CPRA** | California | Biometric data is "sensitive personal information" |
| **EU AI Act** | EU | Prohibits real-time biometric surveillance in public spaces |
| **City Bans** | 16+ US cities including **Boston**, San Francisco, Portland | Ban on government/police use |

---

## 4. Camera Sources -- Boston Focus

### Boston-Specific Cameras

| Source | Quality | Format | Access |
|--------|---------|--------|--------|
| EarthCam Salesforce Tower | 4K PTZ | Streaming | Enterprise API |
| SkylineWebcams Boston | 1080p | HLS | Embed |
| TheBostonWebcam | HD | Streaming | Web |
| MassDOT Traffic Cams | 640x480 | JPEG (1 frame/120s) | TrafficLand API |
| Windy.com Boston | Variable | JPEG + HLS | API (have key) |
| MWRA Deer Island | HD | Streaming | Web |
| Hyatt Regency Harbor | HD | Streaming | webcamtaxi.com |
| FAA WeatherCams BOS | Medium | JPEG | Public |
| Harvard Science Center | HD | Streaming | SkylineWebcams |
| NBC10/CBS/WCVB | 720-1080p | HLS | Web streams |

### Higher-Quality National Sources

| Source | Quality | Coverage | Pricing |
|--------|---------|----------|---------|
| **EarthCam** | 4K PTZ, archive, object detection | Construction, landmarks | Enterprise |
| **Nexar CityStream** | Street-level, continuously refreshed | 1000+ US cities | Enterprise |
| **TrafficLand** | RTSP streaming, 12-15fps, h.264 | 200+ cities, 25K+ cams | Contact |
| **INRIX Camera API** | 640x480+ configurable | Nationwide US | Token auth |
| **Vizzion** | JPEG at requested size | 30+ countries, 100K+ cams | Contact |

### Facial Recognition Camera Requirements

| Requirement | Pixels Between Eyes | Use Case |
|-------------|-------------------|----------|
| Minimum detection | ~15 px | Face detection only |
| Template extraction | 32 px | Basic matching |
| Reliable recognition | 40-80 px | Automated matching |
| High-quality ID | 160 px | Forensic-grade |
| Optimal | 400 px | Maximum useful resolution |

**Minimum frame rate**: 15-30 fps for moving subjects
**Practical range**: 3-20 meters for reliable recognition
**Verdict**: Almost NO publicly accessible camera meets facial recognition requirements. Public cameras are wide-angle, distant, low-res -- the opposite of what FR needs.

---

## 5. Satellite Imagery -- Live & Near-Real-Time

### The Physical Reality

**10-second refresh at high resolution is impossible from space.**

- LEO satellites (all high-res): orbit at 400-800km, 7.5 km/s, pass over a point for minutes only. Best constellations: 15-40 passes/day = 30-90 minute gaps.
- GEO satellites (GOES): continuous stare, 30-60 second refresh, but 500m resolution from 35,786km. Cannot see objects.

### Commercial Providers

| Provider | Resolution | Revisit | Cost |
|----------|-----------|---------|------|
| **Maxar WorldView Legion** | 31cm | 15-40x/day | $$$$ (SecureWatch subscription) |
| **BlackSky Gen-3** | 35cm | Hourly | $$$ (Spectra platform) |
| **Planet SkySat** | 50cm | 10-12x/day | $$ (Python SDK) |
| **Capella Space (SAR)** | 25cm | 3-5x/day | $$$ (works through clouds/night) |
| **ICEYE (SAR)** | 16cm Gen-4 | Multiple/day | $$$$ |
| **Airbus Pleiades Neo** | 30cm | 2x/day | $$$ (30min delivery via laser downlink) |
| **Satellogic** | 70cm | 8x/day | $$ |

### Free Sources

| Source | Resolution | Refresh | API |
|--------|-----------|---------|-----|
| **GOES-16/18 Mesoscale** | 500m | 30-60 seconds | AWS S3 (noaa-goes16) |
| **GOES CONUS** | 500m-2km | 5 minutes | AWS S3 |
| **Sentinel-2** | 10m | 3-5 days | Sentinel Hub / Copernicus |
| **Landsat 8/9** | 30m (15m pan) | 8 days | USGS EarthExplorer |
| **NASA GIBS** | Variable | 3-5 hours | WMTS (no auth needed) |
| **NASA FIRMS** | ~375m | <60 seconds (US fire) | REST API (free key) |

### Non-Satellite Persistent Alternatives

| Platform | Resolution | Duration | Coverage |
|----------|-----------|----------|----------|
| **Tethered Aerostats** (TCOM) | cm-level video | 30+ days | ~40km radius |
| **WAMI Aircraft** (PSS) | Vehicle-trackable | Hours | 25 sq mi |
| **HAPS** (Airbus Zephyr) | 18cm | Weeks-months | ~40x30km |
| **Drones** | 4K+ | 30-60 min | Small area |

### Integration APIs

**STAC (SpatioTemporal Asset Catalog):**
- Microsoft Planetary Computer: `https://planetarycomputer.microsoft.com/api/stac/v1/`
- Copernicus: `https://datahub.creodias.eu/stac/`
- Python: `pystac-client` package

**GOES via Python:**
```python
from goes2go import GOES
G = GOES(satellite=16, product="ABI-L2-CMIPF", domain="C")
ds = G.latest()
```

**NASA GIBS WMTS:**
```
https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/
  MODIS_Terra_CorrectedReflectance_TrueColor/default/
  {Date}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg
```

**Sentinel Hub Process API:**
```
POST https://sh.dataspace.copernicus.eu/api/v1/process
Authorization: Bearer {token}
```
