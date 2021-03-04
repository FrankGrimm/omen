
function markButton(btn) {
    $(btn).removeClass("btn-info");
    $(btn).removeClass("btn-primary");
    $(btn).removeClass("btn-success");
    $(btn).removeClass("btn-light");
    $(btn).addClass("btn-dark tag_current_choice");
}

function hotkeyTitles() {
    const hotkeyMap = {
        "anno_nav_next": "&rarr;",
        "anno_nav_prev": "&larr;",
        "anno_nav_random": "R",
    }

    const hotkeyEntities = {}
    
    for (const [dom_target, hotkey_symbol] of Object.entries(hotkeyMap)) {
        const dom_elem = document.getElementById(dom_target);
        if (!dom_elem) { continue; }
        hotkeyEntities[hotkey_symbol] = dom_elem;
    }

    // document.querySelectorAll(".sample_content_tagbtns a.btn").forEach();
    $(".sample_content_tagbtns a.btn").each(function() {
        let $this = $(this);
        if ($this.data("tagidx") !== undefined) {
            hotkeyEntities['' + $this.data("tagidx")] = this;
        }
    });

    console.log("[hotkeys]", hotkeyMap);
    console.log("[hotkeys-entities]", hotkeyEntities);

    for (const [hotkey, dom_elem] of Object.entries(hotkeyEntities)) {
        if (!dom_elem) { continue; }

        const $elem = $(dom_elem);
        if ($elem.data("original-title")) { continue; }

        $elem.attr("title", `hotkey: {hotkey}`);
        $elem.data("content", `hotkey: <span class="kbd">${hotkey}</span>`);

        $elem.popover({
            trigger: "hover focus",
            placement: "left",
            html: true,
            title: "",
            template: '<div class="popover" role="tooltip"><div class="arrow"></div><div class="popover-body"></div></div>'
        });
        $elem.popover("hide");
    }

}

function initAnnoHotkeys() {
    document.addEventListener("keydown", event => {
        if (event.isComposing || event.keyCode === 229) {
            return;
        }
        console.log("[kbd event]", event);
        let $tgtid = null;

        if (event.key === "ArrowRight") {
            $tgtid = 'anno_nav_next';
        }
        if (event.key === "ArrowLeft") {
            $tgtid = 'anno_nav_prev';
        }
        if (event.key === "R" || event.key === "r") {
            $tgtid = 'anno_nav_random';
        }
        let $tgtbtn = null;
        if ($tgtid) {
            $tgtbtn = $("#" + $tgtid);
        }
        if (event.keyCode > 48 && event.keyCode <= 57) {
            let tagoffset = event.keyCode - 48 - 1;
            if (tagoffset < tagcount) {
                $("a.btn").each(function() {
                    let $this = $(this);
                    if ($this.data("tagidx") == tagoffset) {
                        $tgtbtn = $(this);
                    }
                });
            }
        }
        if ($tgtbtn && $tgtbtn[0]) { 
            markButton($tgtbtn[0]);
            $tgtbtn[0].click();
        }
    });
}

function initTagButton(btn) {
    console.log("initialize tag action button", btn);
    const targetHref = btn.getAttribute("href");
    btn.addEventListener("click", function(evt) {
        evt.preventDefault();
        markButton(btn);

        fetch(targetHref + "&contentonly=1", {
            method: 'GET',
            mode: 'cors',
            cache: 'no-cache',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json'
            },
            redirect: 'follow',
            referrerPolicy: 'no-referrer',
        })
        .then(response => response.text())
        .then(annotationResponse => {
            if (window.history && window.history.pushState) {
                window.history.pushState({"from": window.location.href, "to": targetHref}, "Annotation", targetHref);
            }
            console.log("received annotation response data");
            // replace content area
            const containerTarget = document.getElementById("pagebody");
            containerTarget.innerHTML = annotationResponse;
            // rebind button events for the new content
            initTagButtons();
            // make sure flashed messages are handled if any were added
            initAlerts();
        });

        return false;
    });
}

function initTagButtons() {
    document.querySelectorAll(".sample_content_tagbtns a.btn").forEach(initTagButton);
}

document.addEventListener("DOMContentLoaded",function() {
    initAnnoHotkeys();
    initTagButtons();
    hotkeyTitles();
});
