// Mantenimiento: el anillo cuenta los segundos que faltan para que la página se recargue sola
// (la etiqueta <meta http-equiv="refresh"> de la página hace la recarga aunque esto no corra).
(function () {
  var meta = document.querySelector('meta[http-equiv="refresh"]');
  var valor = document.getElementById("valor");
  var texto = document.getElementById("texto");
  if (!meta || !valor || !texto) return;
  var TOTAL = parseInt(meta.getAttribute("content"), 10) || 30, resto = TOTAL;
  function pintar() {
    valor.style.strokeDashoffset = 1 - resto / TOTAL;
    texto.textContent = resto > 0 ? "Nuevo intento en " + resto + " s" : "Comprobando…";
  }
  pintar();
  setInterval(function () { if (resto > 0) { resto--; pintar(); } }, 1000);
})();
