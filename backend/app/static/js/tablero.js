/* Tablero gerencial: pestañas, filtros y tema de los graficos.

   Los graficos llegan del servidor con la paleta clara. En tema oscuro
   cada tono se cambia por su par de la paleta oscura (mismo orden,
   validada sobre #0f172a) y se ajustan textos y rejilla; al volver al
   claro se restaura la figura original. */
(function () {
    "use strict";

    var CLARO_A_OSCURO = {
        "#0a8a64": "#16a87b",
        "#2a78d6": "#3987e5",
        "#eb6834": "#d95926",
        "#6250d6": "#9085e9",
        "#eda100": "#c98500",
        "#e87ba4": "#d55181",
        "#d03b3b": "#ff6b61",
        "#94a3b8": "#64748b",
        "#ffffff": "#0f172a",
        "rgba(10,138,100,0.08)": "rgba(22,168,123,0.14)",
        "#e6f4ef": "#0d2a22",
        "#a9dcc9": "#13523f",
        "#5fb99a": "#1a7d5f",
        "#1f8f6c": "#22b383",
        "#0b5a45": "#6ff0c0"
    };

    function oscuro() {
        return document.documentElement.getAttribute("data-tema") === "oscuro";
    }

    function cambiarColores(texto) {
        return texto.replace(/"(#[0-9a-fA-F]{6}|rgba\([^"]+\))"/g, function (todo, color) {
            var nuevo = CLARO_A_OSCURO[color.toLowerCase().replace(/\s+/g, "")];
            return nuevo ? '"' + nuevo + '"' : todo;
        });
    }

    // Clic en una barra, celda o serie: filtra todo el informe por ese valor.
    function escucharClic(grafico) {
        var contenedor = grafico.closest("[data-filtro-dim]");
        if (!contenedor || grafico._tfClic || !grafico.on) return;
        grafico._tfClic = true;
        grafico.on("plotly_click", function (ev) {
            var punto = ev.points && ev.points[0];
            if (!punto) return;
            var valor = contenedor.dataset.filtroPor === "serie" ? punto.data.name : punto.y;
            if (valor === undefined || valor === null || valor === "Otros") return;
            filtrarPor(contenedor.dataset.filtroDim, String(valor));
        });
    }

    function filtrarPor(dim, valor) {
        var form = document.getElementById("tb-filtros");
        if (!form) return;
        var selector = form.querySelector('select[name="s_' + CSS.escape(dim) + '"]');
        if (selector && Array.prototype.some.call(selector.options, function (o) { return o.value === valor; })) {
            selector.value = valor;
        } else {
            var extra = document.getElementById("tb-extra");
            var previo = form.querySelector('input[type=hidden][name="s_' + CSS.escape(dim) + '"]');
            if (previo) previo.closest(".tb-chip-filtro").remove();
            var chip = document.createElement("span");
            chip.className = "tb-chip-filtro";
            chip.textContent = dim.replace(/_/g, " ") + ": " + valor + " ";
            var oculto = document.createElement("input");
            oculto.type = "hidden";
            oculto.name = "s_" + dim;
            oculto.value = valor;
            var quitar = document.createElement("button");
            quitar.type = "button";
            quitar.setAttribute("data-tb-quitar", "");
            quitar.setAttribute("aria-label", "Quitar filtro " + dim);
            quitar.textContent = "×";
            chip.appendChild(oculto);
            chip.appendChild(quitar);
            extra.appendChild(chip);
        }
        contarFiltros();
        htmx.trigger(form, "cambio");
        form.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    function tematizar(grafico) {
        if (!window.Plotly || !grafico.data || !grafico.layout) return false;
        escucharClic(grafico);
        if (!grafico._tfOriginal) {
            grafico._tfOriginal = JSON.stringify({ data: grafico.data, layout: grafico.layout });
        }
        var modo = oscuro() ? "oscuro" : "claro";
        if (grafico._tfModo === modo) return true;
        grafico._tfModo = modo;

        var figura = JSON.parse(modo === "oscuro" ? cambiarColores(grafico._tfOriginal) : grafico._tfOriginal);
        if (modo === "oscuro") {
            figura.layout.font = Object.assign({}, figura.layout.font, { color: "#94a3b8" });
            figura.layout.hoverlabel = { bgcolor: "#0f172a", bordercolor: "#31435c", font: { color: "#e2e8f0", size: 12 } };
            (figura.layout.annotations || []).forEach(function (a) {
                a.font = Object.assign({}, a.font, { color: "#cbd5e1" });
            });
        }
        window.Plotly.react(grafico, figura.data, figura.layout);
        return true;
    }

    // Los graficos se dibujan con un script propio al insertarse; se
    // reintenta unos cuadros hasta que Plotly termina de montarlos.
    function tematizarTodos(raiz, intentos) {
        var pendientes = 0;
        (raiz || document).querySelectorAll(".js-plotly-plot, .plotly-graph-div").forEach(function (g) {
            if (!tematizar(g)) pendientes += 1;
        });
        if (pendientes && (intentos || 0) < 30) {
            requestAnimationFrame(function () { tematizarTodos(raiz, (intentos || 0) + 1); });
        }
    }

    new MutationObserver(function () { tematizarTodos(document); })
        .observe(document.documentElement, { attributes: true, attributeFilter: ["data-tema"] });

    document.addEventListener("htmx:afterSettle", function (e) { tematizarTodos(e.target); });
    document.addEventListener("DOMContentLoaded", function () { tematizarTodos(document); });

    // ── pestañas ────────────────────────────────────────────────────────
    function activar(nombre) {
        var filtros = document.getElementById("tb-filtros");
        if (!filtros) return;
        filtros.querySelector('input[name="nombre"]').value = nombre;
        document.querySelectorAll(".tb-pestana").forEach(function (b) {
            b.setAttribute("aria-selected", b.dataset.seccion === nombre ? "true" : "false");
        });
        try {
            var url = new URL(window.location.href);
            url.searchParams.set("seccion", nombre);
            history.replaceState(null, "", url);
        } catch (err) { /* sin History API el tablero sigue funcionando */ }
        htmx.trigger(filtros, "cambio");
    }

    document.addEventListener("click", function (e) {
        var pestana = e.target.closest(".tb-pestana");
        if (pestana) {
            activar(pestana.dataset.seccion);
            return;
        }

        var quitar = e.target.closest("[data-tb-quitar]");
        if (quitar) {
            quitar.closest(".tb-chip-filtro").remove();
            contarFiltros();
            htmx.trigger(document.getElementById("tb-filtros"), "cambio");
            return;
        }

        var limpiar = e.target.closest("[data-tb-limpiar]");
        if (limpiar) {
            var form = document.getElementById("tb-filtros");
            form.querySelectorAll("select, input[type=date]").forEach(function (c) { c.value = ""; });
            form.querySelectorAll(".tb-chip-filtro").forEach(function (c) { c.remove(); });
            contarFiltros();
            htmx.trigger(form, "cambio");
            return;
        }

        var chip = e.target.closest("[data-formula]");
        if (chip) {
            var area = document.getElementById("formula");
            if (area) {
                area.value = chip.dataset.formula;
                area.focus();
            }
            return;
        }

        if (e.target.closest("[data-tb-imprimir]")) window.print();
    });

    // Marca los filtros en uso y actualiza el contador.
    function contarFiltros() {
        var form = document.getElementById("tb-filtros");
        var contador = document.getElementById("tb-contador");
        if (!form || !contador) return;
        var n = 0;
        form.querySelectorAll("select, input[type=date]").forEach(function (c) {
            c.classList.toggle("activo", !!c.value);
            if (c.value) n += 1;
        });
        n += form.querySelectorAll(".tb-chip-filtro").length;
        contador.textContent = n ? n + (n > 1 ? " filtros activos" : " filtro activo") : "";
    }

    document.addEventListener("change", function (e) {
        if (e.target.closest("#tb-filtros")) contarFiltros();
    });

    // La guia queda plegada para quien ya la leyo.
    document.addEventListener("DOMContentLoaded", function () {
        var guia = document.getElementById("tb-guia");
        if (!guia) return;
        try {
            if (localStorage.getItem("taskflow-guia") === "plegada") guia.open = false;
        } catch (err) { /* sin almacenamiento la guia aparece abierta */ }
        guia.addEventListener("toggle", function () {
            try { localStorage.setItem("taskflow-guia", guia.open ? "abierta" : "plegada"); } catch (err) {}
        });
    });

    // Cierra las ayudas abiertas al hacer clic fuera de ellas.
    document.addEventListener("click", function (e) {
        document.querySelectorAll(".tb-ayuda[open]").forEach(function (d) {
            if (!d.contains(e.target)) d.open = false;
        });
    });

    // ── carga por arrastre ──────────────────────────────────────────────
    document.addEventListener("DOMContentLoaded", function () {
        var zona = document.querySelector(".tb-carga");
        if (!zona) return;
        var entrada = document.getElementById(zona.getAttribute("for"));
        ["dragenter", "dragover"].forEach(function (ev) {
            zona.addEventListener(ev, function (e) { e.preventDefault(); zona.classList.add("arrastrando"); });
        });
        ["dragleave", "drop"].forEach(function (ev) {
            zona.addEventListener(ev, function () { zona.classList.remove("arrastrando"); });
        });
        zona.addEventListener("drop", function (e) {
            e.preventDefault();
            if (e.dataTransfer.files.length) {
                entrada.files = e.dataTransfer.files;
                entrada.form.requestSubmit();
            }
        });
    });
})();
