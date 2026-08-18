"""
aldia_mcp - Capa de integracion MCP para ALdia.

Expone las operaciones del sistema de gestion comercial ALdia como herramientas
MCP, para que un asistente de IA pueda consultar y operar el negocio.

El servidor habla con la API REST de ALdia por HTTP: NO importa el backend ni
toca la base de datos, de modo que funciona igual contra una instalacion local
o remota.
"""

__version__ = "1.0.0"
