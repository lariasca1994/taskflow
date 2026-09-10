(function () {
    "use strict";
    var CLAVE = "taskflow-tema";
    var raiz = document.documentElement;

    function aplicar(tema) {
        raiz.setAttribute("data-tema", tema);
    }

    var guardado = null;
    try {
        guardado = localStorage.getItem(CLAVE);
    } catch (err) {
        /* almacenamiento no disponible: seguimos con la preferencia del sistema */
    }

    var prefiereOscuro = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    aplicar(guardado || (prefiereOscuro ? "oscuro" : "claro"));

    document.addEventListener("DOMContentLoaded", function () {
        var boton = document.getElementById("alternar-tema");
        if (!boton) return;
        boton.addEventListener("click", function () {
            var actual = raiz.getAttribute("data-tema") === "oscuro" ? "claro" : "oscuro";
            aplicar(actual);
            try {
                localStorage.setItem(CLAVE, actual);
            } catch (err) {
                /* sin almacenamiento persistente, el tema no sobrevive un refresco */
            }
        });
    });
})();
