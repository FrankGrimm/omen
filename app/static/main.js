$(document).ready(function() {

    document.getElementById("sidebar-brandlink").addEventListener("click", function() {
        const smenu = document.getElementById("sidebar-menu");
        $(smenu).toggleClass("d-sm-block", 500);
        console.log("foobar");
    });

});
