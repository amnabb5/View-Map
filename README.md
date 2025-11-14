# 🌍 View Map
**Offline + Online Mapping Application (Python + JS/HTML/CSS)**

View Map is a hybrid mapping tool that works fully **offline** using a 50GB local map dataset and also provides **online search**, **image metadata detection**, and **drive-time estimation**.

---
<img width="1913" height="891" alt="Screenshot 2025-11-07 184734" src="https://github.com/user-attachments/assets/0010b595-87c0-4d73-a3c8-493f32a98156" />

## ✨ Features

### 🔹 Offline Map Mode  
- Works using **raw coordinates** (latitude/longitude)  
- Renders a **real map stored locally (~50GB)**  
- Requires **no internet**  
- Very fast thanks to direct file-based access (Python)

### 🔹 Online Search Mode  
- Search locations by name:  
  *“London, England”*, *“Tokyo, Japan”*, etc.  
- Converts name → coordinates  
- Displays location on the map  
- Shows **estimated driving time** and distance  

### 🔹 Image Metadata (EXIF) Mode  
Upload an image to:  
- Extract GPS coordinates from EXIF  
- Show where the photo was taken on the map  
- If no EXIF:  
  - Use **device GPS**, or  
  - Use **nearest server location**  
- Calculate and display **drive time** to the photo location  

---

## 🛠 Tech Stack

| Layer       | Technology |
|------------|------------|
| Backend    | Python |
| Frontend   | HTML, CSS, JavaScript |
| Storage    | Local 50GB map tiles |
| Function   | Mixed file manipulation + browser UI |

---

## 📁 Project Structure (Example)

view-map/
│
├── backend/
│ └── main.py
│
├── frontend/
│ ├── index.html
│ ├── style.css
│ └── app.js
│
├── maps/
│ └── offline_map_data/ # ~50GB of map files
│
├── images/
│ └── uploads/
│
└── README.md

yaml
Copy code

---

## 🚀 Installation & Usage

### 1. Install Requirements
pip install -r requirements.txt

shell
Copy code

### 2. Run the Application
python main.py

shell
Copy code

### 3. Open in Browser
http://localhost:5000

yaml
Copy code

---

## 🧠 How It Works

### **Offline Mode**
- Input coordinates  
- Python loads map tiles directly  
- JS draws the map  

### **Online Mode**
- Input a location name  
- Fetch coordinates via API  
- Display and center the map  

### **Image Mode**
- Upload image  
- Extract EXIF → get GPS  
- Map centers on detected location  
- Drive-time calculated  

---

## 🔮 Planned Improvements
- Offline route drawing  
- UI upgrade (dark mode + animations)  
- Tile compression system  
- Mobile support  

---

## 🛡 Privacy
- Offline operations never send any data  
- Images stay local unless online features are used  

---

## 👤 Author
Created by **amine**
