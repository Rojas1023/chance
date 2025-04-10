# main.py (archivo principal para Vercel)
from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import random
import pymongo
import json
import pandas as pd
from datetime import datetime
import os
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid

app = FastAPI()

# Configura plantillas y archivos estáticos
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Datos de sorteos (simulados en memoria para simplicidad)
SORTEOS = {
    "2255": {"serie": 1, "premio": 150000000, "fecha": datetime.now().strftime("%d/%m/%Y %H:%M")},
    "3748": {"serie": 2, "premio": 150000000, "fecha": datetime.now().strftime("%d/%m/%Y %H:%M")},
    "4567": {"serie": 3, "premio": 150000000, "fecha": datetime.now().strftime("%d/%m/%Y %H:%M")}
}

VALOR_BILLETE = 10000
session_data = {}  # Para simular la sesión en memoria

# Conexión a MongoDB Atlas
try:
    # Usar la variable de entorno para la cadena de conexión
    uri = os.environ.get("mongodb+srv://jhoansebastianre2005:BRbnBDjzIj9adr6C@cluster0.koay6.mongodb.net/chance_db")
    client = pymongo.MongoClient("mongodb+srv://jhoansebastianre2005:BRbnBDjzIj9adr6C@cluster0.koay6.mongodb.net/chance_db")
    db = client["chance_db"]
    boletos_collection = db["boletos"]
    resultados_collection = db["resultados"]
    
    # Verificar conexión
    client.admin.command('ping')
    print("Conexión exitosa a MongoDB Atlas!")
    
    DB_CONNECTED = True
except Exception as e:
    print(f"Error al conectar a MongoDB Atlas: {e}")
    DB_CONNECTED = False

# Modelos para datos
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
    """Página principal de la aplicación"""
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in session_data:
        # Crear nueva sesión y generar boletos iniciales
        session_id = str(uuid.uuid4())
        session_data[session_id] = {
            "boletos_por_sorteo": generar_boletos_iniciales(),
            "numeros_ganadores": {}
        }
    
    response = templates.TemplateResponse(
        "index.html", 
        {
            "request": request,
            "sorteos": SORTEOS,
            "boletos_por_sorteo": session_data[session_id]["boletos_por_sorteo"],
            "numeros_ganadores": session_data[session_id]["numeros_ganadores"],
            "db_connected": DB_CONNECTED
        }
    )
    
    # Establecer cookie de sesión
    response.set_cookie(key="session_id", value=session_id)
    return response

def generar_boletos_iniciales():
    """Genera 10 boletos aleatorios para cada sorteo"""
    boletos_por_sorteo = {}
    
    for sorteo_id, info in SORTEOS.items():
        # Generar 10 números aleatorios de 4 cifras sin repetir
        numeros = random.sample(range(1000, 10000), 10)
        
        boletos = []
        for num in numeros:
            boleto = {
                "numero": num,
                "sorteo": sorteo_id,
                "premio": info["premio"],
                "fecha_emision": info["fecha"],
                "serie": info["serie"],
                "valor": VALOR_BILLETE
            }
            boletos.append(boleto)
        
        boletos_por_sorteo[sorteo_id] = boletos
        
        # Guardar en MongoDB si está conectado
        if DB_CONNECTED:
            try:
                # Eliminar boletos anteriores de este sorteo
                boletos_collection.delete_many({"sorteo": sorteo_id})
                # Insertar nuevos boletos
                if boletos:
                    boletos_collection.insert_many(boletos)
            except Exception as e:
                print(f"Error al guardar boletos en MongoDB: {e}")
    
    return boletos_por_sorteo

@app.post("/realizar-sorteo")
async def realizar_sorteo(request: Request):
    """Realiza el sorteo para cada grupo de boletos"""
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in session_data:
        raise HTTPException(status_code=400, detail="Sesión no válida")
    
    session = session_data[session_id]
    numeros_ganadores = {}
    numeros_ganadores_totales = []
    
    for sorteo_id, boletos in session["boletos_por_sorteo"].items():
        # Seleccionar un boleto ganador aleatoriamente
        boleto_ganador = random.choice(boletos)
        numeros_ganadores[sorteo_id] = boleto_ganador
        numeros_ganadores_totales.append(boleto_ganador["numero"])
    
    # Verificar si hay números duplicados entre los ganadores
    conteo_ganadores = {}
    for num in numeros_ganadores_totales:
        if num in conteo_ganadores:
            conteo_ganadores[num] += 1
        else:
            conteo_ganadores[num] = 1
    
    # Ajustar premios según duplicados
    for sorteo_id, boleto in numeros_ganadores.items():
        num = boleto["numero"]
        if conteo_ganadores[num] > 1:
            # Dividir el premio entre los ganadores duplicados
            premio_ajustado = boleto["premio"] / conteo_ganadores[num]
            numeros_ganadores[sorteo_id]["premio_ajustado"] = premio_ajustado
        else:
            numeros_ganadores[sorteo_id]["premio_ajustado"] = boleto["premio"]
    
    # Guardar resultados
    session["numeros_ganadores"] = numeros_ganadores
    
    # Guardar en MongoDB si está conectado
    if DB_CONNECTED:
        guardar_resultados_mongodb(numeros_ganadores)
    
    return {"success": True, "resultados": numeros_ganadores}

def guardar_resultados_mongodb(numeros_ganadores):
    """Guarda los resultados del sorteo en MongoDB"""
    try:
        resultados = []
        fecha_sorteo = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        for sorteo_id, ganador in numeros_ganadores.items():
            resultado = {
                "fecha_sorteo": fecha_sorteo,
                "sorteo_id": sorteo_id,
                "numero_ganador": ganador["numero"],
                "premio_original": ganador["premio"],
                "premio_otorgado": ganador.get("premio_ajustado", ganador["premio"]),
                "serie": ganador["serie"]
            }
            resultados.append(resultado)
        
        if resultados:
            resultados_collection.insert_many(resultados)
            print("Resultados guardados en MongoDB")
    except Exception as e:
        print(f"Error al guardar resultados en MongoDB: {e}")

@app.post("/nuevo-juego")
async def nuevo_juego(request: Request):
    """Reinicia la aplicación con nuevos boletos"""
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in session_data:
        raise HTTPException(status_code=400, detail="Sesión no válida")
    
    # Actualizar fecha
    nueva_fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    for sorteo_id in SORTEOS:
        SORTEOS[sorteo_id]["fecha"] = nueva_fecha
    
    # Generar nuevos boletos
    session_data[session_id] = {
        "boletos_por_sorteo": generar_boletos_iniciales(),
        "numeros_ganadores": {}
    }
    
    return {"success": True, "message": "Nuevo juego iniciado"}

@app.get("/exportar/{formato}")
async def exportar_resultados(request: Request, formato: str):
    """Exporta los resultados a un archivo CSV o JSON"""
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in session_data:
        raise HTTPException(status_code=400, detail="Sesión no válida")
    
    session = session_data[session_id]
    numeros_ganadores = session.get("numeros_ganadores", {})
    
    if not numeros_ganadores:
        raise HTTPException(status_code=400, detail="No hay resultados para exportar")
    
    # Crear DataFrame con los resultados
    data = []
    for sorteo_id, ganador in numeros_ganadores.items():
        premio_otorgado = ganador.get("premio_ajustado", ganador["premio"])
        data.append({
            "Sorteo": sorteo_id,
            "Número Ganador": ganador["numero"],
            "Serie": ganador["serie"],
            "Premio Original": ganador["premio"],
            "Premio Otorgado": premio_otorgado,
            "Fecha": SORTEOS[sorteo_id]["fecha"]
        })
    
    df = pd.DataFrame(data)
    fecha_actual = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if formato.lower() == "csv":
        csv_data = df.to_csv(index=False)
        return JSONResponse(content={"data": csv_data, "filename": f"resultados_chance_{fecha_actual}.csv"})
    
    elif formato.lower() == "json":
        json_data = df.to_json(orient="records")
        return JSONResponse(content={"data": json.loads(json_data), "filename": f"resultados_chance_{fecha_actual}.json"})
    
    else:
        raise HTTPException(status_code=400, detail="Formato no soportado")
