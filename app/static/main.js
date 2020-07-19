// since we insert the CSS locally, prevent Chart.js from injecting it
Chart.platform.disableCSSInjection = true;

function initMarkdownEditors() {
    document.querySelectorAll("textarea.with-markdown").forEach((textarea) => {
        const mdeToolbar = [
            {name:"bold", action: SimpleMDE.toggleBold, className: "mdi mdi-format-bold", title: "Bold"},
            {name:"italic", action: SimpleMDE.toggleItalic, className: "mdi mdi-format-italic", title: "Italic"},
            {name:"heading", action: SimpleMDE.toggleHeading1, className: "mdi mdi-format-header-pound", title: "Heading"},
            "|",
            {name:"quote", action: SimpleMDE.toggleBlockquote, className: "mdi mdi-format-quote-open", title: "Quote"},
            {name:"unordered-list", action: SimpleMDE.toggleUnorderedList, className: "mdi mdi-format-list-bulleted", title: "Generic List"},
            {name:"ordered-list", action: SimpleMDE.toggleOrderedList, className: "mdi mdi-format-list-numbered", title: "Numbered List"},
            "|",
            {name:"link", action: SimpleMDE.drawLink, className: "mdi mdi-link-variant", title: "Create Link"},
            "|",
            {name:"preview", action: SimpleMDE.togglePreview, className: "mdi mdi-eye no-disable", title: "Toggle Preview"},
            {name:"guide","action":"https://simplemde.com/markdown-guide", className: "mdi mdi-help-circle-outline", title: "Markdown Guide"},
            "|"];
        const mdeOptions = {
            element: textarea,
            autoDownloadFontAwesome: false,
            autofocus: false,
            autosave: false,
            forceSync: true,
            spellChecker: true,
            toolbar: mdeToolbar
        };
        const mde = new SimpleMDE(mdeOptions);
        window.mde = mde;
    });
}

function initPopovers() {
    const addPopOvers = (elem) => {
        if (!elem.getAttribute("title")) { return; }
        const popoverText = elem.getAttribute("title").trim();
        if (!popoverText) { return; }

        const $elem = $(elem);
        $elem.popover({
            trigger: "hover focus",
            placement: "auto",
            content: popoverText,
            title: "",
            template: '<div class="popover" role="tooltip"><div class="arrow"></div><div class="popover-body"></div></div>'
        });
        
        $elem.hover(function() {
            if ($elem.is(":disabled")) {
                $elem.popover("hide");
            }
        }, function() {
            // blur, do nothing
        });
    };
    
    const titled_links = document.querySelectorAll("a[title]");
    const titled_buttons = document.querySelectorAll("button[title]");
    const nav_items = document.querySelectorAll(".nav-item[title]");
    titled_links.forEach(addPopOvers)
    titled_buttons.forEach(addPopOvers)
    nav_items.forEach(addPopOvers)
}

function initSidebar() {
    const smenu = document.getElementById("sidebar-menu");
    const scompact = document.getElementById("sidebar-compact");
    const $smenu = $(smenu);
    const $scompact = $(scompact);
    const $main = $("main");

    function restoreSidebarState() {
        if (!window.localStorage) { return; }

        const val = window.localStorage.getItem("sidebar-visibility");

        if (val && val === "hidden") {
            $smenu.removeClass("d-none");
            $smenu.removeClass("d-md-block");
            $smenu.hide();
            $scompact.show();

            $main.removeClass("col-md-10 col-lg-10");
            $main.addClass("col-md-12 col-lg-12");
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
        const initial_visibility = $smenu.is(":visible");
        $smenu.removeClass("d-none");
        $smenu.removeClass("d-md-block");

        if (initial_visibility) {
            $smenu.hide();
            $scompact.show();
            $main.removeClass("col-md-10 col-lg-10");
            $main.addClass("col-md-12 col-lg-12");
        } else {
            $smenu.show();
            $scompact.hide();
            $main.addClass("col-md-10 col-lg-10");
            $main.removeClass("col-md-12 col-lg-12");
        }

        storeSidebarState(!initial_visibility);

        console.log("toggled sidebar");
    });
}

function initMarkdownContent() {
    const mdTargets = [".description_modal_text"];
    mdTargets.forEach((mdTarget) => {
        document.querySelectorAll(mdTarget).forEach((elem) => {
            const mdcontent = elem.textContent.trim();
            const mdconverted = marked(mdcontent);
            elem.innerHTML = mdconverted;
        });
    });
}

window.addEventListener('DOMContentLoaded', (event) => {

    initSidebar();

    initPopovers();

    $('select').selectpicker();

    initMarkdownEditors();
    initMarkdownContent();

});
