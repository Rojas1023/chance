# /api/index.py (archivo principal para Vercel)
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import random
import pymongo
import json
import pandas as pd
from datetime import datetime
import os
from pydantic import BaseModel
import uuid

app = FastAPI()

# Configura plantillas y archivos estáticos
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# Simulación de sorteos
SORTEOS = {
    "2255": {"serie": 1, "premio": 150000000, "fecha": datetime.now().strftime("%d/%m/%Y %H:%M")},
    "3748": {"serie": 2, "premio": 150000000, "fecha": datetime.now().strftime("%d/%m/%Y %H:%M")},
    "4567": {"serie": 3, "premio": 150000000, "fecha": datetime.now().strftime("%d/%m/%Y %H:%M")}
}

VALOR_BILLETE = 10000
session_data = {}

# Conexión MongoDB
try:
    uri = os.environ.get("MONGO_URI")  # Usa una variable de entorno segura
    client = pymongo.MongoClient(uri)
    db = client["chance_db"]
    boletos_collection = db["boletos"]
    resultados_collection = db["resultados"]
    client.admin.command('ping')
    DB_CONNECTED = True
except Exception as e:
    print(f"Error al conectar a MongoDB: {e}")
    DB_CONNECTED = False

class Boleto(BaseModel):
    numero: int
    sorteo: str
    premio: float
    fecha_emision: str
    serie: int
    valor: float

class Resultado(BaseModel):
    fecha_sorteo: str
    sorteo_id: str
    numero_ganador: int
    premio_original: float
    premio_otorgado: float
    serie: int

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in session_data:
        session_id = str(uuid.uuid4())
        session_data[session_id] = {
            "boletos_por_sorteo": generar_boletos_iniciales(),
            "numeros_ganadores": {}
        }

    response = templates.TemplateResponse("index.html", {
        "request": request,
        "sorteos": SORTEOS,
        "boletos_por_sorteo": session_data[session_id]["boletos_por_sorteo"],
        "numeros_ganadores": session_data[session_id]["numeros_ganadores"],
        "db_connected": DB_CONNECTED
    })

    response.set_cookie(key="session_id", value=session_id)
    return response

def generar_boletos_iniciales():
    boletos_por_sorteo = {}
    for sorteo_id, info in SORTEOS.items():
        numeros = random.sample(range(1000, 10000), 10)
        boletos = [{
            "numero": num,
            "sorteo": sorteo_id,
            "premio": info["premio"],
            "fecha_emision": info["fecha"],
            "serie": info["serie"],
            "valor": VALOR_BILLETE
        } for num in numeros]

        boletos_por_sorteo[sorteo_id] = boletos

        if DB_CONNECTED:
            try:
                boletos_collection.delete_many({"sorteo": sorteo_id})
                if boletos:
                    boletos_collection.insert_many(boletos)
            except Exception as e:
                print(f"Error al guardar boletos en MongoDB: {e}")

    return boletos_por_sorteo

@app.post("/realizar-sorteo")
async def realizar_sorteo(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in session_data:
        raise HTTPException(status_code=400, detail="Sesión no válida")

    session = session_data[session_id]
    numeros_ganadores = {}
    numeros_totales = []

    for sorteo_id, boletos in session["boletos_por_sorteo"].items():
        ganador = random.choice(boletos)
        numeros_ganadores[sorteo_id] = ganador
        numeros_totales.append(ganador["numero"])

    conteo = {}
    for num in numeros_totales:
        conteo[num] = conteo.get(num, 0) + 1

    for sorteo_id, boleto in numeros_ganadores.items():
        repeticiones = conteo[boleto["numero"]]
        boleto["premio_ajustado"] = boleto["premio"] / repeticiones if repeticiones > 1 else boleto["premio"]

    session["numeros_ganadores"] = numeros_ganadores

    if DB_CONNECTED:
        guardar_resultados_mongodb(numeros_ganadores)

    return {"success": True, "resultados": numeros_ganadores}

def guardar_resultados_mongodb(numeros_ganadores):
    try:
        fecha = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        resultados = [{
            "fecha_sorteo": fecha,
            "sorteo_id": k,
            "numero_ganador": v["numero"],
            "premio_original": v["premio"],
            "premio_otorgado": v.get("premio_ajustado", v["premio"]),
            "serie": v["serie"]
        } for k, v in numeros_ganadores.items()]

        if resultados:
            resultados_collection.insert_many(resultados)
    except Exception as e:
        print(f"Error al guardar resultados: {e}")

@app.post("/nuevo-juego")
async def nuevo_juego(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in session_data:
        raise HTTPException(status_code=400, detail="Sesión no válida")

    nueva_fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    for sorteo in SORTEOS.values():
        sorteo["fecha"] = nueva_fecha

    session_data[session_id] = {
        "boletos_por_sorteo": generar_boletos_iniciales(),
        "numeros_ganadores": {}
    }

    return {"success": True, "message": "Nuevo juego iniciado"}

@app.get("/exportar/{formato}")
async def exportar_resultados(request: Request, formato: str):
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in session_data:
        raise HTTPException(status_code=400, detail="Sesión no válida")

    resultados = session_data[session_id].get("numeros_ganadores", {})
    if not resultados:
        raise HTTPException(status_code=400, detail="No hay resultados")

    data = []
    for sid, r in resultados.items():
        data.append({
            "Sorteo": sid,
            "Número Ganador": r["numero"],
            "Serie": r["serie"],
            "Premio Original": r["premio"],
            "Premio Otorgado": r.get("premio_ajustado", r["premio"]),
            "Fecha": SORTEOS[sid]["fecha"]
        })

    df = pd.DataFrame(data)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if formato.lower() == "csv":
        return JSONResponse(content={
            "data": df.to_csv(index=False),
            "filename": f"resultados_{timestamp}.csv"
        })
    elif formato.lower() == "json":
        return JSONResponse(content={
            "data": json.loads(df.to_json(orient="records")),
            "filename": f"resultados_{timestamp}.json"
        })
    else:
        raise HTTPException(status_code=400, detail="Formato no válido")
