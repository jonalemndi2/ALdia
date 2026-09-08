# Reglas para agentes

## Publicación

- Nunca ejecutar `git push` directamente en este repositorio.
- Publicar únicamente mediante `./publicar.sh --publicar`.
- Mantener `tests/`, `backend/requirements-dev.txt`, datos comerciales, bases,
  respaldos, credenciales, certificados, claves y archivos locales fuera de Git.
- Antes de publicar, ejecutar las pruebas privadas locales y todos los controles
  de `publicar.sh`; una falla bloquea la publicación.
- No usar `git add -f` para saltar `.gitignore` ni `--no-verify` para evitar el
  control de publicación.
- Si un cambio necesita material privado para validarse, conservar ese material
  sólo en el equipo local y publicar únicamente el código de producción.
