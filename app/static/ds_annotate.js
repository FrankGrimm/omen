
function markButton(btn) {
    $(btn).removeClass("btn-info");
    $(btn).removeClass("btn-primary");
    $(btn).removeClass("btn-success");
    $(btn).removeClass("btn-light");
    $(btn).addClass("btn-dark tag_current_choice");
}

function initAnnoHotkeys() {
    document.addEventListener("keydown", event => {
        if (event.isComposing || event.keyCode === 229) {
            return;
        }
        console.log("kbd", event);
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
});
