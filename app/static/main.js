// since we insert the CSS locally, prevent Chart.js from injecting it
Chart.platform.disableCSSInjection = true;

$(document).ready(function() {

    document.getElementById("sidebar-brandlink").addEventListener("click", function() {
        const smenu = document.getElementById("sidebar-menu");
        $(smenu).toggleClass("d-sm-block", 500);
        $(smenu).toggleClass("d-none", 500);
        console.log("toggled sidebar");
    });

    $(".description_modal_text").each(function(idx, elem) {

        const mdcontent = elem.textContent.trim();
        const mdconverted = marked(mdcontent);
        elem.innerHTML = mdconverted;
    });

    const titled_links = document.querySelectorAll("a[title]");

    titled_links.forEach((elem) => {
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
    });

});
