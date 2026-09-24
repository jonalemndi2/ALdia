# Reglas para agentes

## Publicación

- Nunca ejecutar `git push` directamente en este repositorio.
- Publicar únicamente mediante `./publicar.sh --publicar`.
- Las pruebas de `tests/` son públicas y usan SÓLO datos ficticios. Lo que
  necesite material real (listas de proveedores, casos de un comercio) va en
  `tests/privado/`, que Git ignora y el control de privacidad rechaza.
- Mantener datos comerciales, bases, respaldos, credenciales, certificados,
  claves y archivos locales fuera de Git.
- Antes de publicar, ejecutar la suite completa y todos los controles de
  `publicar.sh`; una falla bloquea la publicación.
- No usar `git add -f` para saltar `.gitignore` ni `--no-verify` para evitar el
  control de publicación.
- Si un cambio necesita material privado para validarse, conservar ese material
  sólo en el equipo local y publicar únicamente el código de producción.
