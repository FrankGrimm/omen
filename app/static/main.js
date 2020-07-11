// since we insert the CSS locally, prevent Chart.js from injecting it
Chart.platform.disableCSSInjection = true;

$(document).ready(function() {

    function restoreSidebarState() {
        if (!window.localStorage) { return; }

        const val = window.localStorage.getItem("sidebar-visibility");

        if (val && val === "hidden") {
            const smenu = document.getElementById("sidebar-menu");
            const scompact = document.getElementById("sidebar-compact");
            const $smenu = $(smenu);
            const $scompact = $(scompact);
            $smenu.removeClass("d-none");
            $smenu.removeClass("d-md-block");
            $smenu.hide();
            $scompact.show();
            $("main").removeClass("col-md-10 col-lg-10");
            $("main").addClass("col-md-12 col-lg-12");
        }
    }
    restoreSidebarState();

    function storeSidebarState(new_state) {
        if (!window.localStorage) { return; }
        if (new_state) {
            window.localStorage.setItem("sidebar-visibility", "visible");
        } else {
            window.localStorage.setItem("sidebar-visibility", "hidden");
        }
    }

    document.getElementById("sidebar-brandlink").addEventListener("click", function() {
        const smenu = document.getElementById("sidebar-menu");
        const scompact = document.getElementById("sidebar-compact");
        const $smenu = $(smenu);
        const $scompact = $(scompact);

        const initial_visibility = $smenu.is(":visible");
        $smenu.removeClass("d-none");
        $smenu.removeClass("d-md-block");

        if (initial_visibility) {
            $smenu.hide();
            $scompact.show();
            $("main").removeClass("col-md-10 col-lg-10");
            $("main").addClass("col-md-12 col-lg-12");
        } else {
            $smenu.show();
            $scompact.hide();
            $("main").addClass("col-md-10 col-lg-10");
            $("main").removeClass("col-md-12 col-lg-12");
        }

        storeSidebarState(!initial_visibility);

        console.log("toggled sidebar");
    });

    $(".description_modal_text").each(function(idx, elem) {

        const mdcontent = elem.textContent.trim();
        const mdconverted = marked(mdcontent);
        elem.innerHTML = mdconverted;
    });

    const addPopOvers = (elem) => {
        if (!elem.getAttribute("title")) { return; }
        const popoverText = elem.getAttribute("title").trim();
        if (!popoverText) { return; }
        $(elem).popover({
            trigger: "hover focus",
            placement: "auto",
            content: popoverText,
            title: "",
            template: '<div class="popover" role="tooltip"><div class="arrow"></div><div class="popover-body"></div></div>'
        });
    };
    
    const titled_links = document.querySelectorAll("a[title]");
    const titled_buttons = document.querySelectorAll("a[title]");
    const nav_items = document.querySelectorAll(".nav-item[title]");
    titled_links.forEach(addPopOvers)
    titled_buttons.forEach(addPopOvers)
    nav_items.forEach(addPopOvers)

    $('select').selectpicker();
});
