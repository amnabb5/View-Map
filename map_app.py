import os
import sys
import folium
import webbrowser
import json
import base64
import socket
import requests
from datetime import datetime
from flask import Flask, render_template_string, request
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from folium.plugins import MarkerCluster, HeatMap, MeasureControl, Fullscreen

# === Enhanced EXIF Extractor Class ===
class ExifGeoLocator:
    def __init__(self, image_path):
        self.image_path = image_path
        self.exif = self.get_exif()
        self.lat, self.lon = self.extract_lat_lon()
        self.metadata = self.extract_metadata()
    
    def get_exif(self):
        try:
            print(f"📖 Opening image: {self.image_path}")
            img = Image.open(self.image_path)
            print(f"📐 Image size: {img.size}, Format: {img.format}")
            
            exif_data = None
            
            if hasattr(img, '_getexif'):
                exif_data = img._getexif()
                print(f"🔍 Method 1 (_getexif): {'Found' if exif_data else 'Empty'}")
            
            if not exif_data and hasattr(img, 'getexif'):
                exif_data = img.getexif()
                print(f"🔍 Method 2 (getexif): {'Found' if exif_data else 'Empty'}")
            
            if not exif_data and hasattr(img, 'info'):
                exif_data = img.info.get('exif', {})
                print(f"🔍 Method 3 (info): {'Found' if exif_data else 'Empty'}")
            
            if not exif_data:
                print(f"⚠️ No EXIF data found in image")
                return {}
            
            readable = {}
            for tag_id, value in exif_data.items():
                tag = TAGS.get(tag_id, tag_id)
                readable[tag] = value
            
            print(f"✅ Found {len(readable)} EXIF tags")
            if 'GPSInfo' in readable:
                print(f"✅ GPS Info found!")
            else:
                print(f"⚠️ No GPSInfo tag in EXIF")
            
            return readable
        except Exception as e:
            print(f"❌ Error reading EXIF: {e}")
            return {}
    
    def get_gps_info(self):
        gps_info = self.exif.get("GPSInfo")
        if not gps_info:
            return None
        
        gps_parsed = {}
        try:
            if isinstance(gps_info, dict):
                for key, value in gps_info.items():
                    decoded = GPSTAGS.get(key, key)
                    gps_parsed[decoded] = value
            elif hasattr(gps_info, 'items'):
                for key, value in gps_info.items():
                    decoded = GPSTAGS.get(key, key)
                    gps_parsed[decoded] = value
            else:
                for key in gps_info:
                    value = gps_info[key]
                    decoded = GPSTAGS.get(key, key)
                    gps_parsed[decoded] = value
            
            return gps_parsed
        except Exception as e:
            print(f"❌ Error parsing GPS: {e}")
            return None
    
    def dms_to_decimal(self, dms, ref):
        def to_float(r):
            try:
                return float(r)
            except Exception:
                num, den = r
                return num / den
        
        degrees = to_float(dms[0])
        minutes = to_float(dms[1])
        seconds = to_float(dms[2])
        decimal = degrees + minutes / 60.0 + seconds / 3600.0
        
        if ref in ["S", "W"]:
            decimal = -decimal
        return decimal
    
    def extract_lat_lon(self):
        gps = self.get_gps_info()
        if not gps:
            return None, None
        
        lat_tuple = gps.get("GPSLatitude")
        lat_ref = gps.get("GPSLatitudeRef")
        lon_tuple = gps.get("GPSLongitude")
        lon_ref = gps.get("GPSLongitudeRef")
        
        if lat_tuple and lat_ref and lon_tuple and lon_ref:
            try:
                lat = self.dms_to_decimal(lat_tuple, lat_ref)
                lon = self.dms_to_decimal(lon_tuple, lon_ref)
                return lat, lon
            except Exception as e:
                print(f"❌ Error converting coordinates: {e}")
                return None, None
        
        return None, None
    
    def extract_metadata(self):
        metadata = {}
        metadata['camera'] = self.exif.get('Model', 'Unknown')
        metadata['make'] = self.exif.get('Make', 'Unknown')
        metadata['datetime'] = self.exif.get('DateTime', 'Unknown')
        metadata['width'] = self.exif.get('ExifImageWidth', 'Unknown')
        metadata['height'] = self.exif.get('ExifImageHeight', 'Unknown')
        
        gps = self.get_gps_info()
        if gps:
            altitude = gps.get('GPSAltitude')
            if altitude:
                try:
                    alt_value = float(altitude[0]) / float(altitude[1]) if isinstance(altitude, tuple) else float(altitude)
                    metadata['altitude'] = f"{alt_value:.1f}m"
                except:
                    metadata['altitude'] = 'Unknown'
            else:
                metadata['altitude'] = 'Unknown'
        else:
            metadata['altitude'] = 'Unknown'
        
        return metadata
    
    def reverse_geocode(self):
        if self.lat is None or self.lon is None:
            return None
        
        geolocator = Nominatim(user_agent="smart_map_ui")
        try:
            location = geolocator.reverse((self.lat, self.lon), language="en", timeout=10)
            return location.address if location else None
        except (GeocoderTimedOut, GeocoderServiceError):
            return None

if getattr(sys, 'frozen', False):
    base_path = os.path.dirname(sys.executable)
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

tile_folder = os.path.join(base_path, 'tiles')

if os.path.exists(tile_folder):
    zoom_levels = [d for d in os.listdir(tile_folder) if os.path.isdir(os.path.join(tile_folder, d)) and d.isdigit()]
    if not zoom_levels:
        print(f"⚠️ No zoom folders found in: {tile_folder}")
        zoom_levels = []
    else:
        print(f"✅ Found zoom levels: {', '.join(sorted(zoom_levels))}")
else:
    print(f"⚠️ Tiles folder not found: {tile_folder}")
    zoom_levels = []

app = Flask(__name__)

def check_internet_connection():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        print("✅ Internet connection detected")
        return True
    except OSError:
        print("⚠️ No internet connection")
        return False

def get_user_location():
    print("\n🌍 Attempting to detect your real location...")
    
    try:
        print("🔍 Trying ipapi.co...")
        response = requests.get('https://ipapi.co/json/', timeout=5)
        if response.status_code == 200:
            data = response.json()
            lat = data.get('latitude')
            lon = data.get('longitude')
            city = data.get('city', 'Unknown')
            region = data.get('region', 'Unknown')
            country = data.get('country_name', 'Unknown')
            
            if lat and lon:
                print(f"✅ Location detected: {city}, {region}, {country}")
                print(f"📍 Coordinates: {lat}, {lon}")
                return (lat, lon, f"{city}, {region}, {country}")
    except Exception as e:
        print(f"❌ ipapi.co failed: {e}")
    
    try:
        print("🔍 Trying ip-api.com...")
        response = requests.get('http://ip-api.com/json/', timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                lat = data.get('lat')
                lon = data.get('lon')
                city = data.get('city', 'Unknown')
                region = data.get('regionName', 'Unknown')
                country = data.get('country', 'Unknown')
                
                if lat and lon:
                    print(f"✅ Location detected: {city}, {region}, {country}")
                    print(f"📍 Coordinates: {lat}, {lon}")
                    return (lat, lon, f"{city}, {region}, {country}")
    except Exception as e:
        print(f"❌ ip-api.com failed: {e}")
    
    try:
        print("🔍 Trying ipinfo.io...")
        response = requests.get('https://ipinfo.io/json', timeout=5)
        if response.status_code == 200:
            data = response.json()
            loc = data.get('loc', '').split(',')
            city = data.get('city', 'Unknown')
            region = data.get('region', 'Unknown')
            country = data.get('country', 'Unknown')
            
            if len(loc) == 2:
                lat, lon = float(loc[0]), float(loc[1])
                print(f"✅ Location detected: {city}, {region}, {country}")
                print(f"📍 Coordinates: {lat}, {lon}")
                return (lat, lon, f"{city}, {region}, {country}")
    except Exception as e:
        print(f"❌ ipinfo.io failed: {e}")
    
    print("⚠️ Could not detect location")
    return None

def get_gps_from_image(image_path):
    try:
        print(f"\n{'='*60}")
        print(f"🔍 Processing image file: {image_path}")
        print(f"{'='*60}")
        
        if not os.path.exists(image_path):
            print(f"❌ File does not exist!")
            return None
        
        print(f"✅ File exists, size: {os.path.getsize(image_path)} bytes")
        
        locator = ExifGeoLocator(image_path)
        
        if locator.lat and locator.lon:
            print(f"✅ SUCCESS: GPS found at {locator.lat}, {locator.lon}")
            
            try:
                img = Image.open(image_path)
                img.thumbnail((200, 200), Image.Resampling.LANCZOS)
                
                from io import BytesIO
                buffer = BytesIO()
                img.save(buffer, format='JPEG', quality=85)
                img_str = base64.b64encode(buffer.getvalue()).decode()
                
                print(f"✅ Created thumbnail")
            except Exception as e:
                print(f"⚠️ Could not create thumbnail: {e}")
                img_str = None
            
            return {
                'coords': (locator.lat, locator.lon),
                'metadata': locator.metadata,
                'address': locator.reverse_geocode(),
                'image_data': img_str
            }
        else:
            print(f"❌ FAILED: No valid GPS coordinates extracted")
        
        return None
    except Exception as e:
        print(f"❌ EXCEPTION: Error extracting GPS data: {e}")
        return None

html_form = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Smart Map Viewer Pro</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  :root {
    --gradient-primary: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    --gradient-success: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
    --bg-dark: #0a0a1f;
    --card-bg: rgba(255, 255, 255, 0.98);
    --text-dark: #1a1a2e;
    --text-light: #6b7280;
    --shadow-xl: 0 30px 80px rgba(102, 126, 234, 0.5);
  }
  body {
    font-family: 'Inter', sans-serif;
    background: var(--bg-dark);
    min-height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 20px;
    position: relative;
    overflow-x: hidden;
  }
  .stars { position: absolute; width: 100%; height: 100%; overflow: hidden; }
  .star {
    position: absolute;
    width: 2px;
    height: 2px;
    background: white;
    border-radius: 50%;
    animation: twinkle 3s infinite;
  }
  @keyframes twinkle { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }
  .orb {
    position: absolute;
    border-radius: 50%;
    filter: blur(80px);
    opacity: 0.4;
    animation: float 25s ease-in-out infinite;
  }
  .orb-1 {
    width: 500px;
    height: 500px;
    background: linear-gradient(135deg, #667eea, #764ba2);
    top: -250px;
    left: -250px;
  }
  .orb-2 {
    width: 400px;
    height: 400px;
    background: linear-gradient(135deg, #f093fb, #f5576c);
    bottom: -200px;
    right: -200px;
    animation-delay: 8s;
  }
  @keyframes float {
    0%, 100% { transform: translate(0, 0) rotate(0deg); }
    33% { transform: translate(40px, -40px) rotate(120deg); }
    66% { transform: translate(-30px, 30px) rotate(240deg); }
  }
  .container { position: relative; z-index: 1; max-width: 900px; width: 100%; }
  .card {
    background: var(--card-bg);
    backdrop-filter: blur(30px);
    padding: 50px 45px;
    border-radius: 32px;
    box-shadow: var(--shadow-xl);
    position: relative;
    animation: slideUp 0.9s cubic-bezier(0.16, 1, 0.3, 1);
    border: 1px solid rgba(255, 255, 255, 0.3);
  }
  @keyframes slideUp {
    from { opacity: 0; transform: translateY(60px) scale(0.95); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }
  .card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 50%;
    transform: translateX(-50%);
    width: 70%;
    height: 5px;
    background: var(--gradient-primary);
    border-radius: 0 0 25px 25px;
    box-shadow: 0 5px 25px rgba(102, 126, 234, 0.6);
  }
  .header { text-align: center; margin-bottom: 40px; }
 .icon-wrapper {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100px;
    height: 100px;
    background: var(--gradient-primary);
    border-radius: 30px;
    margin: 0 auto 24px auto; /* 👈 centers it horizontally */
    box-shadow: 0 15px 40px rgba(102, 126, 234, 0.4);
    animation: pulse 3s ease-in-out infinite;
    position: relative;
}
.icon-wrapper::after {
    content: '🗺️';
    font-size: 48px;
    text-align: center;
}

  h1 {
    font-size: 36px;
    font-weight: 800;
    background: var(--gradient-primary);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 10px;
  }
  .subtitle { color: var(--text-light); font-size: 16px; font-weight: 500; }
  .stats-bar { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 35px; }
  .stat-card {
    background: linear-gradient(135deg, rgba(102, 126, 234, 0.08), rgba(118, 75, 162, 0.08));
    padding: 18px;
    border-radius: 16px;
    text-align: center;
    border: 1px solid rgba(102, 126, 234, 0.2);
    transition: all 0.3s ease;
  }
  .stat-card:hover { transform: translateY(-3px); box-shadow: 0 8px 20px rgba(102, 126, 234, 0.2); }
  .stat-number {
    font-size: 26px;
    font-weight: 700;
    background: var(--gradient-primary);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 5px;
  }
  .stat-label {
    font-size: 12px;
    color: var(--text-light);
    font-weight: 600;
    text-transform: uppercase;
  }
  .form-group { margin-bottom: 25px; }
  label {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 600;
    font-size: 14px;
    color: var(--text-dark);
    margin-bottom: 12px;
  }
  select, input {
    width: 100%;
    padding: 15px 20px;
    border: 2px solid #e5e7eb;
    border-radius: 16px;
    font-size: 15px;
    font-family: inherit;
    outline: none;
    transition: all 0.3s;
    background: white;
    color: var(--text-dark);
    font-weight: 500;
  }
  select:focus, input:focus {
    border-color: #667eea;
    box-shadow: 0 0 0 4px rgba(102, 126, 234, 0.12);
    transform: translateY(-2px);
  }
  #inputs { margin-top: 20px; }
  .input-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin-bottom: 12px;
  }
  .single-input { margin-bottom: 12px; }
  .feature-toggle {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
    margin: 25px 0;
  }
  .toggle-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    background: rgba(102, 126, 234, 0.05);
    border-radius: 12px;
    cursor: pointer;
    transition: all 0.3s ease;
  }
  .toggle-item:hover { background: rgba(102, 126, 234, 0.1); }
  .toggle-item input[type="checkbox"] { width: 20px; height: 20px; cursor: pointer; }
  .toggle-item label { margin: 0; cursor: pointer; font-size: 13px; font-weight: 600; }
  button {
    width: 100%;
    padding: 18px;
    border: none;
    border-radius: 16px;
    font-size: 17px;
    font-weight: 700;
    cursor: pointer;
    color: white;
    transition: all 0.3s;
    font-family: inherit;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
  }
  button:hover { transform: translateY(-4px); }
  .btn-primary {
    background: var(--gradient-primary);
    box-shadow: 0 12px 35px rgba(102, 126, 234, 0.35);
    margin-top: 15px;
  }
  .btn-secondary {
    background: var(--gradient-success);
    box-shadow: 0 12px 35px rgba(79, 172, 254, 0.35);
    margin-top: 20px;
  }
  .file-input-wrapper { position: relative; overflow: hidden; width: 100%; }
  .file-input-wrapper input[type=file] { position: absolute; left: -9999px; }
  .image-preview-container {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
    gap: 12px;
    margin-top: 20px;
    max-height: 280px;
    overflow-y: auto;
    padding: 12px;
    background: rgba(102, 126, 234, 0.05);
    border-radius: 16px;
    border: 2px dashed rgba(102, 126, 234, 0.2);
  }
  .image-preview-item {
    position: relative;
    aspect-ratio: 1;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.12);
    transition: all 0.3s;
  }
  .image-preview-item:hover { transform: scale(1.08); border-color: #667eea; }
  .image-preview-item img { width: 100%; height: 100%; object-fit: cover; }
  .image-preview-item .remove-btn {
    position: absolute;
    top: 5px;
    right: 5px;
    width: 26px;
    height: 26px;
    border-radius: 50%;
    background: rgba(245, 87, 108, 0.95);
    color: white;
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    opacity: 0;
    transition: all 0.3s;
    padding: 0;
  }
  .image-preview-item:hover .remove-btn { opacity: 1; }
  .file-label {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    width: 100%;
    padding: 45px 25px;
    border: 3px dashed #667eea;
    border-radius: 16px;
    background: linear-gradient(135deg, rgba(102, 126, 234, 0.06), rgba(118, 75, 162, 0.06));
    cursor: pointer;
    transition: all 0.4s;
    font-weight: 700;
    font-size: 16px;
  }
  .file-label:hover { border-color: #764ba2; transform: translateY(-3px); }
  @media (max-width: 768px) {
    .card { padding: 40px 30px; }
    h1 { font-size: 28px; }
    .input-row, .stats-bar, .feature-toggle { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
  <div class="stars" id="stars"></div>
  <div class="orb orb-1"></div>
  <div class="orb orb-2"></div>
  
  <div class="container">
    <div class="card">
      <div class="header">
        <div class="icon-wrapper"></div>
        <h1>Smart Map Viewer Pro</h1>
        <p class="subtitle">Explore locations with real-time geolocation</p>
      </div>

      <div class="stats-bar">
        <div class="stat-card">
          <div class="stat-number" id="locationCount">0</div>
          <div class="stat-label">Locations</div>
        </div>
        <div class="stat-card">
          <div class="stat-number" id="totalDistance">0 km</div>
          <div class="stat-label">Total Distance</div>
        </div>
        <div class="stat-card">
          <div class="stat-number" id="avgDistance">0 km</div>
          <div class="stat-label">Avg Distance</div>
        </div>
      </div>

      <form method="post" enctype="multipart/form-data" id="mapForm" onsubmit="return validateForm()">
        <div class="form-group">
          <label for="mode"><i class="fas fa-compass"></i> Select Mode</label>
          <select name="mode" id="mode" onchange="changeMode()">
            <option value="offline">📍 Offline (Coordinates)</option>
            <option value="online">🌐 Online (Places)</option>
            <option value="image">🖼️ Upload Images</option>
          </select>
        </div>

        <div class="feature-toggle">
          <div class="toggle-item">
            <input type="checkbox" name="cluster" id="cluster" value="1" checked>
            <label for="cluster">🎯 Cluster Markers</label>
          </div>
          <div class="toggle-item">
            <input type="checkbox" name="heatmap" id="heatmap" value="1">
            <label for="heatmap">🔥 Heatmap View</label>
          </div>
          <div class="toggle-item">
            <input type="checkbox" name="measure" id="measure" value="1" checked>
            <label for="measure">📏 Measure Tool</label>
          </div>
          <div class="toggle-item">
            <input type="checkbox" name="fullscreen" id="fullscreen" value="1" checked>
            <label for="fullscreen">🖥️ Fullscreen</label>
          </div>
        </div>

        <div class="form-group" id="manualLocationSection" style="display:none;">
          <label for="manual_location">
            <i class="fas fa-map-pin"></i>
            Manual "Your Location" Override (Optional)
          </label>
          <input type="text" name="manual_location" id="manual_location" placeholder="e.g., Paris, France OR leave empty for auto-detect">
          <p style="font-size: 12px; color: #9ca3af; margin-top: 8px;">💡 Only fill this if auto-detection fails or you want a different reference point</p>
        </div>

        <div id="inputs">
          <div class="input-row">
            <input type="text" name="lat" placeholder="Latitude">
            <input type="text" name="lon" placeholder="Longitude">
          </div>
        </div>

        <button type="button" class="btn-secondary" onclick="addField()">
          <i class="fas fa-plus-circle"></i> Add Another Location
        </button>
        
        <button type="submit" class="btn-primary">
          <i class="fas fa-rocket"></i> Generate Awesome Map
        </button>
      </form>
    </div>
  </div>

<script>
const starsContainer = document.getElementById('stars');
for (let i = 0; i < 100; i++) {
  const star = document.createElement('div');
  star.className = 'star';
  star.style.left = Math.random() * 100 + '%';
  star.style.top = Math.random() * 100 + '%';
  star.style.animationDelay = Math.random() * 3 + 's';
  starsContainer.appendChild(star);
}

let uploadedImages = [];

function addField(){
  let mode = document.getElementById("mode").value;
  let div = document.getElementById("inputs");
  let html = "";
  
  if (mode === "offline") {
    html = '<div class="input-row"><input type="text" name="lat" placeholder="Latitude"><input type="text" name="lon" placeholder="Longitude"></div>';
  } else if (mode === "online") {
    html = '<div class="single-input"><input type="text" name="place" placeholder="City, Country"></div>';
  }
  
  if (mode !== "image") {
    div.insertAdjacentHTML('beforeend', html);
    updateStats();
  }
}

function changeMode(){
  let mode = document.getElementById("mode").value;
  let div = document.getElementById("inputs");
  div.innerHTML = "";
  
  if (mode === "offline") {
    div.innerHTML = '<div class="input-row"><input type="text" name="lat" placeholder="Latitude"><input type="text" name="lon" placeholder="Longitude"></div>';
  } else if (mode === "online") {
    div.innerHTML = '<div class="single-input"><input type="text" name="place" placeholder="City, Country"></div>';
  } else if (mode === "image") {
    div.innerHTML = '<div class="file-input-wrapper"><input type="file" name="images" id="imageInput" accept="image/*" multiple onchange="handleImageUpload()"><label for="imageInput" class="file-label"><i class="fas fa-cloud-upload-alt"></i>Click to Upload Images</label></div><div class="image-preview-container" id="imagePreviewContainer"></div>';
  }
  updateStats();
}

function handleImageUpload() {
  const input = document.getElementById('imageInput');
  const container = document.getElementById('imagePreviewContainer');
  
  Array.from(input.files).forEach((file, index) => {
    const reader = new FileReader();
    const imageId = Date.now() + index + Math.random();
    
    uploadedImages.push({ id: imageId, file: file, name: file.name });
    
    reader.onload = function(e) {
      const previewItem = document.createElement('div');
      previewItem.className = 'image-preview-item';
      previewItem.setAttribute('data-id', imageId);
      previewItem.innerHTML = `
        <img src="${e.target.result}" alt="${file.name}">
        <button class="remove-btn" type="button" onclick="removeImage(${imageId})">×</button>
      `;
      container.appendChild(previewItem);
      updateStats();
    };
    reader.readAsDataURL(file);
  });
  setTimeout(() => { input.value = ''; }, 100);
}

function validateForm() {
  const mode = document.getElementById('mode').value;
  if (mode === 'image') {
    if (!uploadedImages || uploadedImages.length === 0) {
      alert('⚠️ Please select at least one image!');
      return false;
    }
    const formData = new FormData();
    const form = document.getElementById('mapForm');
    const inputs = form.querySelectorAll('input:not([type="file"]), select');
    inputs.forEach(input => {
      if (input.type === 'checkbox') {
        if (input.checked) formData.append(input.name, input.value);
      } else if (input.name && input.value) {
        formData.append(input.name, input.value);
      }
    });
    uploadedImages.forEach(img => formData.append('images', img.file));
    fetch('/', { method: 'POST', body: formData })
      .then(response => response.text())
      .then(html => { document.open(); document.write(html); document.close(); })
      .catch(error => alert('Error uploading images.'));
    return false;
  }
  return true;
}

function removeImage(imageId) {
  uploadedImages = uploadedImages.filter(img => img.id !== imageId);
  const previewItem = document.querySelector(`[data-id="${imageId}"]`);
  if (previewItem) previewItem.remove();
  updateStats();
}

function updateStats() {
  const mode = document.getElementById("mode").value;
  let count = 0;
  if (mode === "image") count = uploadedImages.length;
  else if (mode === "offline") count = document.querySelectorAll('input[name="lat"]').length;
  else if (mode === "online") count = document.querySelectorAll('input[name="place"]').length;
  document.getElementById('locationCount').textContent = count;
}

updateStats();
</script>
</body>
</html>
"""

@app.route("/test-location")
def test_location():
    """Test endpoint to see what location is being detected"""
    loc = get_user_location()
    if loc:
        return f"""
        <html>
        <head>
            <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
        </head>
        <body style="margin:0; font-family:'Inter',sans-serif; background:#0a0a1f; min-height:100vh; display:flex; align-items:center; justify-content:center; padding:20px;">
            <div style="background:rgba(255,255,255,0.98); padding:50px; border-radius:32px; box-shadow:0 30px 80px rgba(102,126,234,0.5); text-align:center; max-width:500px;">
                <h1 style="color:#667eea; margin-bottom:20px;">🌍 Location Detection Test</h1>
                <div style="background:#f0f9ff; padding:20px; border-radius:16px; margin:20px 0; text-align:left;">
                    <p style="margin:10px 0;"><strong>📍 Latitude:</strong> {loc[0]}</p>
                    <p style="margin:10px 0;"><strong>📍 Longitude:</strong> {loc[1]}</p>
                    <p style="margin:10px 0;"><strong>🌆 Location:</strong> {loc[2]}</p>
                </div>
                <p style="color:#6b7280; margin-top:20px;">Check the console for detailed API responses</p>
                <a href="/" style="display:inline-block; margin-top:25px; padding:16px 32px; background:linear-gradient(135deg, #667eea, #764ba2); color:white; text-decoration:none; border-radius:14px; font-weight:700;">Back to App</a>
            </div>
        </body>
        </html>
        """
    return f"""
    <html>
    <head>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    </head>
    <body style="margin:0; font-family:'Inter',sans-serif; background:#0a0a1f; min-height:100vh; display:flex; align-items:center; justify-content:center; padding:20px;">
        <div style="background:rgba(255,255,255,0.98); padding:50px; border-radius:32px; box-shadow:0 30px 80px rgba(102,126,234,0.5); text-align:center; max-width:500px;">
            <h1 style="color:#f5576c; margin-bottom:20px;">⚠️ Location Detection Failed</h1>
            <p style="color:#6b7280; margin:20px 0;">Could not detect your location. All geolocation APIs failed.</p>
            <p style="color:#9ca3af; font-size:14px;">Check the console for detailed error messages</p>
            <a href="/" style="display:inline-block; margin-top:25px; padding:16px 32px; background:linear-gradient(135deg, #667eea, #764ba2); color:white; text-decoration:none; border-radius:14px; font-weight:700;">Back to App</a>
        </div>
    </body>
    </html>
    """

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        mode = request.form.get("mode")
        coords = []
        distances = []
        
        is_online = check_internet_connection()
        use_cluster = request.form.get("cluster") == "1"
        use_heatmap = request.form.get("heatmap") == "1"
        use_measure = request.form.get("measure") == "1"
        use_fullscreen = request.form.get("fullscreen") == "1"

        if mode == "offline":
            lats = request.form.getlist("lat")
            lons = request.form.getlist("lon")
            coords = [(float(lat), float(lon)) for lat, lon in zip(lats, lons) if lat and lon]

            if zoom_levels:
                m = folium.Map(
                    location=[28.0, 3.0],
                    zoom_start=5,
                    tiles=None,
                    min_zoom=min(map(int, zoom_levels)),
                    max_zoom=max(map(int, zoom_levels)),
                    max_bounds=True
                )
                folium.raster_layers.TileLayer(
                    tiles=f'file:///{tile_folder}/{{z}}/{{x}}/{{y}}.png',
                    attr='Offline Tiles',
                    name='Offline Map',
                    overlay=False,
                    control=False,
                    min_zoom=min(map(int, zoom_levels)),
                    max_zoom=max(map(int, zoom_levels))
                ).add_to(m)
            else:
                m = folium.Map(location=[28.0, 3.0], zoom_start=5)

        elif mode == "online":
            places = request.form.getlist("place")
            geolocator = Nominatim(user_agent="smart_map_ui")
            user_location_data = get_user_location()
            
            for place in places:
                if place.strip():
                    location = geolocator.geocode(place)
                    if location:
                        coords.append((location.latitude, location.longitude))
            
            if user_location_data and coords:
                user_location = (user_location_data[0], user_location_data[1])
                location_name = user_location_data[2]
                
                m = folium.Map(location=user_location, zoom_start=6)
                
                folium.Marker(
                    location=user_location,
                    popup=f"""
                    <div style='font-family: Inter, sans-serif; width: 200px;'>
                        <h4 style='margin: 0 0 10px 0; color: #667eea;'>📍 Your Location</h4>
                        <p style='margin: 5px 0; font-size: 13px;'><strong>{location_name}</strong></p>
                    </div>
                    """,
                    icon=folium.Icon(color='red', icon='home', prefix='fa')
                ).add_to(m)
                
                if use_cluster:
                    marker_cluster = MarkerCluster(name='Locations').add_to(m)
                    map_obj = marker_cluster
                else:
                    map_obj = m
                
                for idx, (lat, lon) in enumerate(coords):
                    distance = geodesic(user_location, (lat, lon)).kilometers
                    distances.append(distance)
                    
                    folium.Marker(
                        location=[lat, lon],
                        popup=f"""
                        <div style='font-family: Inter, sans-serif; width: 220px;'>
                            <h4 style='margin: 0 0 10px 0; color: #667eea;'>📍 Location #{idx+1}</h4>
                            <p style='margin: 5px 0; font-size: 13px;'><strong>Coordinates:</strong> {lat:.4f}, {lon:.4f}</p>
                            <p style='margin: 5px 0; font-size: 13px;'><strong>🚗 Distance:</strong> {distance:.2f} km</p>
                            <p style='margin: 5px 0; font-size: 13px;'><strong>⏱️ Est. Drive:</strong> {int(distance / 60 * 60)} min</p>
                        </div>
                        """,
                        icon=folium.Icon(color='blue', icon='info-sign')
                    ).add_to(map_obj)
                    
                    folium.PolyLine(
                        locations=[user_location, [lat, lon]],
                        color='#667eea',
                        weight=3,
                        opacity=0.7,
                        popup=f"Distance: {distance:.2f} km"
                    ).add_to(m)
            else:
                m = folium.Map(location=[28.0, 3.0], zoom_start=5)

        elif mode == "image":
            if 'images' in request.files:
                image_files = request.files.getlist('images')
                images_data = []
                user_location_data = get_user_location()
                user_location = None
                location_name = "Unknown Location"
                
                if user_location_data:
                    user_location = (user_location_data[0], user_location_data[1])
                    location_name = user_location_data[2]
                
                for idx, image_file in enumerate(image_files):
                    if image_file.filename != '':
                        import tempfile
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
                            image_file.save(tmp_file.name)
                            gps_data = get_gps_from_image(tmp_file.name)
                        try:
                            os.remove(tmp_file.name)
                        except:
                            pass
                        
                        if gps_data:
                            images_data.append({
                                'filename': image_file.filename,
                                'coords': gps_data['coords'],
                                'metadata': gps_data['metadata'],
                                'address': gps_data['address'],
                                'image_data': gps_data.get('image_data')
                            })
                            coords.append(gps_data['coords'])
                        else:
                            images_data.append({
                                'filename': image_file.filename,
                                'coords': None,
                                'metadata': None,
                                'address': None,
                                'image_data': None
                            })
                
                if coords:
                    center_lat = sum(c[0] for c in coords) / len(coords)
                    center_lon = sum(c[1] for c in coords) / len(coords)
                    
                    if is_online:
                        m = folium.Map(location=[center_lat, center_lon], zoom_start=12)
                    elif zoom_levels:
                        m = folium.Map(location=[center_lat, center_lon], zoom_start=12, tiles=None)
                        folium.raster_layers.TileLayer(
                            tiles=f'file:///{tile_folder}/{{z}}/{{x}}/{{y}}.png',
                            attr='Offline Tiles',
                            name='Offline Map',
                            overlay=False,
                            control=False,
                            min_zoom=min(map(int, zoom_levels)),
                            max_zoom=max(map(int, zoom_levels))
                        ).add_to(m)
                    else:
                        m = folium.Map(location=[center_lat, center_lon], zoom_start=12)
                    
                    if user_location:
                        folium.Marker(
                            location=user_location,
                            popup=f"""
                            <div style='font-family: Inter, sans-serif; width: 200px;'>
                                <h4 style='margin: 0 0 10px 0; color: #667eea;'>📍 Your Location</h4>
                                <p style='margin: 5px 0; font-size: 13px;'><strong>{location_name}</strong></p>
                            </div>
                            """,
                            icon=folium.Icon(color='red', icon='home', prefix='fa')
                        ).add_to(m)
                    
                    if use_cluster:
                        marker_cluster = MarkerCluster(name='Photos').add_to(m)
                        map_obj = marker_cluster
                    else:
                        map_obj = m
                    
                    for idx, img_data in enumerate(images_data):
                        if img_data['coords']:
                            lat, lon = img_data['coords']
                            metadata = img_data['metadata']
                            address = img_data['address']
                            image_data = img_data.get('image_data')
                            
                            popup_html = f"""
                            <div style='font-family: Inter, sans-serif; width: 300px; max-height: 500px; overflow-y: auto;'>
                            """
                            
                            if image_data:
                                popup_html += f"""
                                <div style='margin-bottom: 12px; text-align: center;'>
                                    <img src='data:image/jpeg;base64,{image_data}' 
                                         style='max-width: 100%; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.2);'>
                                </div>
                                """
                            
                            popup_html += f"""
                                <h4 style='margin: 0 0 12px 0; color: #00f2fe; border-bottom: 2px solid #00f2fe; padding-bottom: 8px;'>
                                    📷 {img_data['filename']}
                                </h4>
                                <div style='background: rgba(79,172,254,0.1); padding: 10px; border-radius: 8px; margin-bottom: 10px;'>
                                    <p style='margin: 5px 0; font-size: 12px;'><strong>📍 Coordinates:</strong> {lat:.6f}, {lon:.6f}</p>
                            """
                            
                            if address:
                                popup_html += f"<p style='margin: 5px 0; font-size: 12px;'><strong>🌍 Location:</strong> {address[:100]}...</p>"
                            
                            if user_location:
                                distance = geodesic(user_location, (lat, lon)).kilometers
                                distances.append(distance)
                                popup_html += f"""
                                <p style='margin: 5px 0; font-size: 12px;'><strong>🚗 Distance from you:</strong> {distance:.2f} km</p>
                                <p style='margin: 5px 0; font-size: 12px;'><strong>⏱️ Est. Drive:</strong> {int(distance / 60 * 60)} min</p>
                                """
                                
                                folium.PolyLine(
                                    locations=[user_location, [lat, lon]],
                                    color='#00f2fe',
                                    weight=3,
                                    opacity=0.6,
                                    popup=f"Distance: {distance:.2f} km"
                                ).add_to(m)
                            
                            popup_html += "</div>"
                            
                            if metadata:
                                popup_html += """
                                <div style='background: rgba(102,126,234,0.1); padding: 10px; border-radius: 8px; margin-bottom: 10px;'>
                                    <h5 style='margin: 0 0 8px 0; color: #667eea;'>📸 Camera Info</h5>
                                """
                                if metadata.get('make') != 'Unknown' and metadata.get('camera') != 'Unknown':
                                    popup_html += f"<p style='margin: 3px 0; font-size: 11px;'><strong>Camera:</strong> {metadata['make']} {metadata['camera']}</p>"
                                if metadata.get('datetime') != 'Unknown':
                                    popup_html += f"<p style='margin: 3px 0; font-size: 11px;'><strong>Date:</strong> {metadata['datetime']}</p>"
                                if metadata.get('width') != 'Unknown' and metadata.get('height') != 'Unknown':
                                    popup_html += f"<p style='margin: 3px 0; font-size: 11px;'><strong>Resolution:</strong> {metadata['width']} x {metadata['height']}</p>"
                                if metadata.get('altitude') != 'Unknown':
                                    popup_html += f"<p style='margin: 3px 0; font-size: 11px;'><strong>Altitude:</strong> {metadata['altitude']}</p>"
                                popup_html += "</div>"
                            
                            popup_html += "</div>"
                            
                            if image_data:
                                icon_html = f"""
                                <div style='position: relative;'>
                                    <div style='width: 60px; height: 60px; border-radius: 50%; overflow: hidden; border: 3px solid #00f2fe; box-shadow: 0 4px 12px rgba(0,242,254,0.5); background: white;'>
                                        <img src='data:image/jpeg;base64,{image_data}' style='width: 100%; height: 100%; object-fit: cover;'>
                                    </div>
                                    <div style='position: absolute; bottom: -5px; right: -5px; background: #00f2fe; border-radius: 50%; width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; box-shadow: 0 2px 8px rgba(0,0,0,0.3);'>
                                        <i class='fa fa-camera' style='color: white; font-size: 10px;'></i>
                                    </div>
                                </div>
                                """
                                custom_icon = folium.DivIcon(html=icon_html)
                                folium.Marker(
                                    location=[lat, lon],
                                    popup=folium.Popup(popup_html, max_width=320),
                                    icon=custom_icon
                                ).add_to(map_obj)
                            else:
                                folium.Marker(
                                    location=[lat, lon],
                                    popup=folium.Popup(popup_html, max_width=320),
                                    icon=folium.Icon(color='green', icon='camera', prefix='fa')
                                ).add_to(map_obj)
                else:
                    no_gps_images = [img['filename'] for img in images_data if not img['coords']]
                    return f"""
                    <html>
                    <head>
                        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
                    </head>
                    <body style="margin:0; font-family:'Inter',sans-serif; background:#0a0a1f; min-height:100vh; display:flex; align-items:center; justify-content:center; padding:20px;">
                        <div style="background:rgba(255,255,255,0.98); padding:50px; border-radius:32px; box-shadow:0 30px 80px rgba(102,126,234,0.5); text-align:center; max-width:550px;">
                            <div style="width: 80px; height: 80px; margin: 0 auto 20px; background: linear-gradient(135deg, #f5576c, #764ba2); border-radius: 20px; display: flex; align-items: center; justify-content: center; font-size: 40px;">⚠️</div>
                            <h3 style="font-size:32px; font-weight:800; background:linear-gradient(135deg, #f5576c, #764ba2); -webkit-background-clip:text; -webkit-text-fill-color:transparent; margin-bottom:25px;">No GPS Data Found</h3>
                            <p style="color:#6b7280; font-size:17px; margin-bottom:25px;">The images don't contain GPS coordinates.</p>
                            <a href="/" style="display:inline-block; padding:16px 32px; background:linear-gradient(135deg, #667eea, #764ba2); color:white; text-decoration:none; border-radius:14px; font-weight:700; font-size: 16px; box-shadow: 0 10px 30px rgba(102,126,234,0.3);">Try Again</a>
                        </div>
                    </body>
                    </html>
                    """

        if not coords:
            return """
            <html>
            <head>
                <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
            </head>
            <body style="margin:0; font-family:'Inter',sans-serif; background:#0a0a1f; min-height:100vh; display:flex; align-items:center; justify-content:center;">
                <div style="background:rgba(255,255,255,0.98); padding:50px; border-radius:32px; box-shadow:0 30px 80px rgba(102,126,234,0.5); text-align:center; max-width:450px;">
                    <div style="width: 80px; height: 80px; margin: 0 auto 20px; background: linear-gradient(135deg, #f5576c, #764ba2); border-radius: 20px; display: flex; align-items: center; justify-content: center; font-size: 40px;">⚠️</div>
                    <h3 style="font-size:32px; font-weight:800; background:linear-gradient(135deg, #f5576c, #764ba2); -webkit-background-clip:text; -webkit-text-fill-color:transparent; margin-bottom:20px;">No Locations Provided</h3>
                    <p style="color:#6b7280; font-size:17px;">Please provide at least one location.</p>
                    <a href="/" style="display:inline-block; margin-top:25px; padding:16px 32px; background:linear-gradient(135deg, #667eea, #764ba2); color:white; text-decoration:none; border-radius:14px; font-weight:700; font-size: 16px; box-shadow: 0 10px 30px rgba(102,126,234,0.3);">Go Back</a>
                </div>
            </body>
            </html>
            """

        if mode == "offline":
            for lat, lon in coords:
                folium.Marker(
                    location=[lat, lon], 
                    popup=f"""
                    <div style='font-family: Inter, sans-serif; width: 200px;'>
                        <h4 style='margin: 0 0 10px 0; color: #667eea;'>📍 Location</h4>
                        <p style='margin: 5px 0; font-size: 13px;'><strong>Coordinates:</strong> {lat}, {lon}</p>
                    </div>
                    """
                ).add_to(m)

        if use_heatmap and coords:
            HeatMap(coords, name='Heatmap', min_opacity=0.3, radius=25, blur=35, gradient={
                0.0: '#4facfe', 0.5: '#f093fb', 1.0: '#f5576c'
            }).add_to(m)
        
        if use_measure:
            MeasureControl(position='topleft', primary_length_unit='kilometers').add_to(m)
        
        if use_fullscreen:
            Fullscreen(position='topright').add_to(m)
        
        folium.LayerControl().add_to(m)

        map_file = "map_result.html"
        m.save(map_file)
        
        total_distance = sum(distances) if distances else 0
        avg_distance = total_distance / len(distances) if distances else 0
        
        webbrowser.open_new_tab('file://' + os.path.realpath(map_file))
        
        return f"""
        <html>
        <head>
            <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        </head>
        <body style="margin:0; font-family:'Inter',sans-serif; background:#0a0a1f; min-height:100vh; display:flex; align-items:center; justify-content:center; padding:20px;">
            <div style="background:rgba(255,255,255,0.98); padding:50px; border-radius:32px; box-shadow:0 30px 80px rgba(102,126,234,0.5); text-align:center; max-width:500px;">
                <div style="width: 90px; height: 90px; margin: 0 auto 25px; background: linear-gradient(135deg, #4facfe, #00f2fe); border-radius: 22px; display: flex; align-items: center; justify-content: center; font-size: 45px; box-shadow: 0 15px 40px rgba(79,172,254,0.4);">✅</div>
                <h3 style="font-size:34px; font-weight:800; background:linear-gradient(135deg, #4facfe, #00f2fe); -webkit-background-clip:text; -webkit-text-fill-color:transparent; margin-bottom:20px;">Map Generated!</h3>
                <p style="color:#6b7280; font-size:17px; margin-bottom:30px;">Your interactive map has been created successfully.</p>
                
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 30px;">
                    <div style="background: linear-gradient(135deg, rgba(102,126,234,0.08), rgba(118,75,162,0.08)); padding: 20px; border-radius: 16px; border: 1px solid rgba(102,126,234,0.2);">
                        <div style="font-size: 24px; font-weight: 700; background: linear-gradient(135deg, #667eea, #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">{len(coords)}</div>
                        <div style="font-size: 11px; color: #6b7280; font-weight: 600; margin-top: 5px;">LOCATIONS</div>
                    </div>
                    <div style="background: linear-gradient(135deg, rgba(102,126,234,0.08), rgba(118,75,162,0.08)); padding: 20px; border-radius: 16px; border: 1px solid rgba(102,126,234,0.2);">
                        <div style="font-size: 24px; font-weight: 700; background: linear-gradient(135deg, #667eea, #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">{total_distance:.1f}</div>
                        <div style="font-size: 11px; color: #6b7280; font-weight: 600; margin-top: 5px;">TOTAL KM</div>
                    </div>
                    <div style="background: linear-gradient(135deg, rgba(102,126,234,0.08), rgba(118,75,162,0.08)); padding: 20px; border-radius: 16px; border: 1px solid rgba(102,126,234,0.2);">
                        <div style="font-size: 24px; font-weight: 700; background: linear-gradient(135deg, #667eea, #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">{avg_distance:.1f}</div>
                        <div style="font-size: 11px; color: #6b7280; font-weight: 600; margin-top: 5px;">AVG KM</div>
                    </div>
                </div>
                
                <a href="/" style="display:inline-block; padding:16px 32px; background:linear-gradient(135deg, #667eea, #764ba2); color:white; text-decoration:none; border-radius:14px; font-weight:700; font-size: 16px; box-shadow: 0 10px 30px rgba(102,126,234,0.3);">
                    <i class="fas fa-map-marked-alt"></i> Create Another Map
                </a>
            </div>
        </body>
        </html>
        """

    return render_template_string(html_form)

if __name__ == "__main__":
    import threading
    
    def open_browser():
        webbrowser.open('http://127.0.0.1:5000')
    
    threading.Timer(1.5, open_browser).start()
    
    print("🚀 Starting Smart Map Viewer Pro...")
    print("🌐 Opening browser at http://127.0.0.1:5000")
    app.run(port=5000, debug=False, use_reloader=False) 