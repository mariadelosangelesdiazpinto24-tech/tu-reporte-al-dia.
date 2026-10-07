import os
import unicodedata
from fastapi import FastAPI, Request, Form, File, UploadFile, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import sqlite3

app = FastAPI()

# Configurar carpetas
if not os.path.exists("uploads"):
    os.makedirs("uploads")

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="templates")

# Normalizador de agencias
def normalizar_agencia(nombre: str) -> str:
    nombre = nombre.strip().upper()
    if nombre.startswith("AGENCIA "):
        nombre = nombre[8:]
    nombre = ''.join(
        c for c in unicodedata.normalize('NFD', nombre)
        if unicodedata.category(c) != 'Mn'
    )
    return nombre.strip()

# Base de datos
def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reportes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agencia TEXT,
            fecha TEXT,
            factura TEXT,
            monto REAL,
            comprobante TEXT,
            estado TEXT DEFAULT 'PENDIENTE'
        )
    """)
    conn.commit()
    conn.close()

init_db()

@app.get("/", response_class=HTMLResponse)
def get_login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def post_login(request: Request, usuario: str = Form(...), clave: str = Form(...)):
    usuario_norm = normalizar_agencia(usuario)
    
    if usuario_norm == "ADMIN" and clave == "admin123":
        response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="user", value="ADMIN")
        return response
    
    if clave == "1234":
        response = RedirectResponse(url=f"/agencia?nombre={usuario_norm}", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="user", value=usuario_norm)
        return response
        
    return templates.TemplateResponse("login.html", {"request": request, "error": "Credenciales inválidas"})

@app.get("/agencia", response_class=HTMLResponse)
def get_agencia(request: Request, nombre: str = ""):
    return templates.TemplateResponse("agencia.html", {"request": request, "agencia": nombre})

@app.post("/reportar")
async def post_reportar(
    request: Request,
    agencia: str = Form(...),
    fecha: str = Form(...),
    factura: str = Form(...),
    monto: float = Form(...),
    comprobante: UploadFile = File(...)
):
    ruta_foto = f"uploads/{comprobante.filename}"
    with open(ruta_foto, "wb") as f:
        f.write(await comprobante.read())
        
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO reportes (agencia, fecha, factura, monto, comprobante) VALUES (?, ?, ?, ?, ?)",
        (agencia, fecha, factura, monto, ruta_foto)
    )
    conn.commit()
    conn.close()
    
    return templates.TemplateResponse("agencia.html", {
        "request": request, 
        "agencia": agencia, 
        "mensaje": "¡Pago reportado con éxito!"
    })

@app.get("/admin", response_class=HTMLResponse)
def get_admin(request: Request):
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reportes ORDER BY id DESC")
    reportes = cursor.fetchall()
    conn.close()
    
    return templates.TemplateResponse("admin.html", {"request": request, "reportes": reportes})
