
function markButton(btn) {
    $(btn).removeClass("btn-info");
    $(btn).removeClass("btn-primary");
    $(btn).removeClass("btn-success");
    $(btn).removeClass("btn-light");
    $(btn).addClass("btn-dark tag_current_choice");
}

function hotkeyTitles() {
    // make sure all other and previous popovers are hidden
    $("[data-toggle='popover']").popover('hide');

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
        $elem.data("toggle", "popover");

        $elem.popover({
            trigger: "hover",
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
        if (window.KBD_IN_INPUT) {
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
            let tagoffset = event.keyCode - 48;
            $("a.btn").each(function() {
                let $this = $(this);
                if ($this.data("tagidx") == tagoffset) {
                    $tgtbtn = $(this);
                }
            });
        }
        if ($tgtbtn && $tgtbtn[0]) { 
            markButton($tgtbtn[0]);
            $tgtbtn[0].click();
        }
    });
}

function submitAnnotationChange(targetHref) {
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
        $(".popover").hide();
        // replace content area
        const containerTarget = document.getElementById("pagebody");
        containerTarget.innerHTML = annotationResponse;
        // rebind events for the new content
        initTagButtons();
        initTextEditors();
        initCopyID();
        hotkeyTitles();
        window.KBD_IN_INPUT = false;

        // make sure flashed messages are handled if any were added
        initAlerts();
    });
}

function initTagButton(btn) {
    console.log("initialize tag action button", btn);
    const targetHref = btn.getAttribute("href");
    btn.addEventListener("click", function(evt) {
        evt.preventDefault();
        markButton(btn);

        const taskMetaElement = evt.target.closest(".annotation_task_tags");

        submitAnnotationChange(targetHref);

        return false;
    });
}

function initTagButtons() {
    document.querySelectorAll(".sample_content_tagbtns a.btn").forEach(initTagButton);
}

function initTextEditor(elem) {
    elem.addEventListener("focus", (evt) => {
        window.KBD_IN_INPUT = true;
    });
    elem.addEventListener("blur", (evt) => {
        window.KBD_IN_INPUT = false;

        
        const target = evt.target;
        const cur_value = evt.target.closest(".annotation_task_text").dataset.curvalue;
        const new_value = evt.target.value;
        if (new_value != cur_value) {
            const api_target = evt.target.closest(".annotation_task_text").dataset.target + "&set_value=" + encodeURIComponent(new_value);
            submitAnnotationChange(api_target);
        }
    });

    elem.addEventListener("keyup", (evt) => {
        const target = evt.target;
        const cur_value = evt.target.closest(".annotation_task_text").dataset.curvalue;
        const new_value = evt.target.value;
        if (new_value != cur_value) {
            target.classList.add("text_input_changed");
        } else {
            target.classList.remove("text_input_changed");
        }
    });
}

function updateSelectionInput(selectedText) {
    console.log(selectedText);
    document.querySelectorAll(".anno_textinput_copyselection").forEach((btn) => {
        if (selectedText) {
            btn.disabled = false;
        } else {
            btn.disabled = true;
        }
        btn.dataset.content = selectedText;
    });
}

function textEditorSelectionEvents(domTarget) {
    document.addEventListener("selectionchange", () => {
        const selection = window.getSelection();
        
        if (selection.type === "Range" && domTarget.contains(selection.anchorNode)) {
            const selectedText = selection.toString();
            updateSelectionInput(selectedText);
            return;
        } else {
            updateSelectionInput("");
        }
    });
}

function initApplySelection(btn) {
    btn.addEventListener("click", (evt) => {
        if (btn.dataset.content === null) { return; }

        const target = btn.closest(".input-group").querySelector(".anno_textinput");
        target.value = btn.dataset.content;
        target.focus();
        target.blur();
    });
}

function initTextEditors() {
    document.querySelectorAll(".anno_textinput").forEach(initTextEditor);
    document.querySelectorAll(".anno_textinput_copyselection").forEach(initApplySelection);
    document.querySelectorAll("blockquote.sampletext").forEach(textEditorSelectionEvents);
}

function initCopyID() {
    const copyIDcontent = document.getElementById("sample_metadata_id");
    const copyIndicator = document.getElementById("sample_metadata_id_copied");
    copyIndicator.style.display = "none";

    copyIDcontent.addEventListener("click", (event) => {
        event.preventDefault();
        
        const tempInput = document.createElement("input");
        tempInput.type = "text";
        tempInput.value = copyIDcontent.textContent;
        document.body.appendChild(tempInput);
        tempInput.focus();
        tempInput.setSelectionRange(0, tempInput.value.length);
        const copySuccess = document.execCommand('copy');
        tempInput.blur();
        tempInput.remove();
        copyIndicator.style.display = "inline-block";
        return false;
    });
}

document.addEventListener("DOMContentLoaded",function() {
    initAnnoHotkeys();
    initTagButtons();
    initCopyID();
    initTextEditors();
    hotkeyTitles();
    window.KBD_IN_INPUT = false;
});

window.addEventListener("popstate", function(e) {
    window.location = window.location.href;
});
