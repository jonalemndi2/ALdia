# Política de seguridad

ALdía maneja facturación electrónica ante AFIP, datos de clientes con su CUIT,
cuentas corrientes y hashes de contraseñas. Un problema de seguridad acá no es
un inconveniente técnico: es la contabilidad de un comercio real.

## Cómo reportar una vulnerabilidad

**Si el problema es explotable, no abras un issue público.** Usá los
[avisos de seguridad privados de GitHub][advisory]: quedan visibles solo para
quien mantiene el proyecto hasta que haya un arreglo publicado.

[advisory]: https://github.com/Jonalemndi2/ALdia/security/advisories/new

Para todo lo demás —una duda, algo que te parece flojo pero no sabés explotar,
una mejora defensiva— abrí un issue normal.

En los dos casos, **nunca incluyas datos reales de ningún comercio**: ni CUIT,
ni nombres de clientes, ni importes facturados, ni el archivo `aldia.db`. Si
necesitás mostrar un caso, inventá los datos. Un reporte de seguridad que filtra
la base de un comercio es peor que el problema que reporta.

Ayuda mucho que incluyas: qué versión estás usando, cómo reproducirlo paso a
paso, y qué llega a hacer un atacante que aprovecha esto.

## Qué está dentro del alcance

- **Autenticación y sesiones**: cualquier forma de operar sin token válido,
  fabricarse uno, o seguir usando una sesión que debería estar cerrada.
- **Autorización**: que un rol acceda a un módulo que no le corresponde, o que
  el rol `auditor` logre modificar algo. La regla del proyecto es que el
  navegador no es una barrera: todo se valida en el servidor.
- **Integridad de la auditoría**: cualquier manera de escribir, borrar o alterar
  el registro desde la aplicación, o de ejecutar una operación sin dejar rastro.
  También cuenta que una operación quede **atribuida a la persona equivocada**.
- **Dinero y stock**: que una secuencia de operaciones deje un saldo, un asiento
  de caja o una existencia distintos de lo que corresponde. Incluye reejecutar
  una operación que debía ejecutarse una sola vez.
- **Facturación electrónica**: cualquier cosa que exponga el certificado de
  AFIP o su clave privada, o que permita pedir un CAE sin autorización.
- **Datos de clientes**: cualquier ruta que devuelva información a quien no
  debería verla.
- El **servidor MCP** (`mcp/`) y las cabeceras con las que un agente declara su
  origen, que son entrada no confiable como cualquier otra.

## Qué NO es una vulnerabilidad

Estas son decisiones tomadas a propósito y documentadas:

- **Que el sistema en HTTP plano sea interceptable.** El README lo dice sin
  vueltas: para exponerlo a internet **hace falta HTTPS** con un proxy inverso.
  La instalación por defecto es para una red local.
- **Que quien tenga acceso al archivo `backend/aldia.db` pueda editarlo por
  fuera de la aplicación.** Está explicado en la sección "Límites honestos" del
  README: ahí la protección son los permisos del sistema operativo y las copias
  de seguridad, no la aplicación.
- **Que la contraseña inicial `admin`/`admin123` sea pública.** Es pública a
  propósito, está en el README, y el sistema **no deja operar** hasta que se
  cambie. Si encontrás una forma de saltear esa obligación, eso sí es un
  reporte válido y nos interesa mucho.
- Un usuario administrador haciendo cosas de administrador. El rol tiene acceso
  total por diseño; lo que sí importa es que **quede auditado**.

## Si ya se te filtró algo

Si un certificado de AFIP, la clave `backend/.aldia_secret` o la base de datos
llegaron a un repositorio público, borrarlos en un commit nuevo **no alcanza**:
siguen estando en el historial. Hay que reescribirlo, y además:

- Rotar la clave de sesión (borrar `backend/.aldia_secret` y reiniciar, o
  definir `ALDIA_SECRET_KEY`). Eso invalida todos los tokens emitidos.
- Volver a tramitar el certificado ante AFIP: con la clave privada, un tercero
  puede facturar en nombre del comercio.
- Cambiar las contraseñas de todos los usuarios.
