$(document).ready(function() {

    document.getElementById("sidebar-brandlink").addEventListener("click", function() {
        const smenu = document.getElementById("sidebar-menu");
        $(smenu).toggleClass("d-sm-block", 500);
        console.log("foobar");
    });

    $(".description_modal_text").each(function(idx, elem) {

        const mdcontent = elem.textContent.trim();
        const mdconverted = marked(mdcontent);
        elem.innerHTML = mdconverted;
    });

});
