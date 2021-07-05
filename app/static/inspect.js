function initChartPalette() {
    const user_colors = {
        white: 'rgb(255, 255, 255)',
        red: 'rgb(255, 99, 132)',
        orange: 'rgb(255, 159, 64)',
        yellow: 'rgb(255, 205, 86)',
        green: 'rgb(75, 192, 192)',
        blue: 'rgb(54, 162, 235)',
        purple: 'rgb(153, 102, 255)',
        gray: 'rgb(201, 203, 207)',
    };
    const palette_colors = {};

    const styles = getComputedStyle(document.documentElement);

    for (var i = 0; i < styles.length; i++) {
        const style_key = styles[i];
        if (!style_key) { continue; }

        if (style_key.startsWith("--tag_color_")) {
            let value = styles.getPropertyValue(style_key);
            value = `rgb(${value})`
            const color_name = style_key.substring("--tag_color_".length)
            user_colors[color_name] = value;
        }
        if (style_key.startsWith("--palette_")) {
            const value = styles.getPropertyValue(style_key);
            const color_name = style_key.substring("--palette_".length)

            if (!(color_name in user_colors)) {
                palette_colors[color_name] = value;
            }
        }
    }

    const result_palette = {
        "user": user_colors,
        "palette": palette_colors
    };
    return result_palette;
}

window.chartColors = initChartPalette();

function initOverviewChart(target) {
    const ctx = document.getElementById(target);
    if (!ctx) {
        console.log("skipping chart initialization, target not found in DOM");
        return;
    }
    
    const config = {
        type: 'doughnut',
        data: {
            datasets: [],
            labels: []
        },
        options: {
            tooltips: {
                callbacks: {
                    label: function(tooltipItem, data) {
                        const datasetLabel = data.datasets[tooltipItem.datasetIndex].label || '';
                        const lbl = data.labels[tooltipItem.index];
                        const value = data.datasets[tooltipItem.datasetIndex].data[tooltipItem.index] || 0;
                        return datasetLabel + ': ' + lbl + " " + value;
                    }
                }
            },
            responsive: true,
            legend: {
                position: "top",
            },
            animation: {
                animateScale: true,
                animateRotate: true
            },
            title: {
                display: true,
                text: "Annotation Distribution"
            },
            circumference: Math.PI,
            rotation: -Math.PI
        }
    };

    const overviewChart = new Chart(ctx, config);

    if (ACTIVE_TASK_ID) {
        fetch(window.OMEN_BASE + "dataset/" + ACTIVE_DATASET_ID + "/" + ACTIVE_TASK_ID + "/overview.json")
            .then(response => response.json())
            .then(overviewData => {
                updateOverviewChart(overviewChart, overviewData, config);
                updateAnnotatorAgreement(overviewData);
            });
    }

    return overviewChart;
}

const show_all_annotators = document.getElementById("show_all_annotators");
if (show_all_annotators) {
    show_all_annotators.addEventListener("click", () => {
        updateOverviewChart(overviewChart, overviewDataCache, overviewChartConfig, "all");
    });
}
const show_individual_annotators = document.getElementById("show_individual_annotators");
if (show_individual_annotators) { 
    show_individual_annotators.addEventListener("click", () => {
        updateOverviewChart(overviewChart, overviewDataCache, overviewChartConfig, "single");
    });
}

const overviewChart = initOverviewChart("overview-chart");
let overviewDataCache = null;
let overviewChartConfig = null;

function updateAnnotatorAgreement(overviewData) {
    if (!overviewData || !overviewData.fleiss) {
        return;
    }

    const value_target = document.getElementById("anno_fleiss_value");
    const kappa_val = overviewData.fleiss.kappa;
    value_target.textContent = kappa_val;
    if (kappa_val >= 0.0 && kappa_val <= 1.0) {
        const kappa_hue = (kappa_val * 120).toString(10);
        value_target.parentNode.style.backgroundColor = `hsl(${kappa_hue}, 100%, 50%)`;
    }

    document.getElementById("anno_fleiss_text").textContent = `(${overviewData.fleiss.interpretation})`;

}

function updateOverviewChart(overviewChart, overviewData, config, mode)  {
    if (!overviewData) { 
        return;
    }
    overviewDataCache = overviewData;
    overviewChartConfig = config;

    // mode = mode || 'all';
    mode = mode || 'single';
    config.data.labels = [...overviewData.tags];

    if (mode === 'single') {
        // config.data.labels.push("N/A");
    }

    overviewChart.data.datasets = [];
    overviewChart.options.title.text = "Annotations";

    const idx_to_palette_color = {
    };

    function randomColor(target_index) {
        const used_colors = Object.values(idx_to_palette_color);
        const available_colors = Object.keys(window.chartColors.palette);
        const num_colors = available_colors.length;

        let result_color = null;
        let attempt = 0;

        while (attempt < num_colors && !result_color) {
            attempt++;

            const try_index = available_colors[Math.floor(num_colors * Math.random())];
            const try_color = window.chartColors.palette[try_index];
            if (try_color in window.chartColors.user) { continue; }
            if (try_color in used_colors) { continue; }

            result_color = try_color;
        }
        if (!result_color) { 
            return "white";
        }

        idx_to_palette_color[target_index] = result_color;
        return result_color;
    }

    function getColor(tag_color, tag_idx) {
        const cols = window.chartColors;

        if (tag_color && tag_color in cols.user) {
            return cols.user[tag_color];
        }

        if (tag_idx in idx_to_palette_color) {
            return idx_to_palette_color[tag_idx];
        }

        return randomColor(tag_idx); 
    }

    if (mode === 'all') {
        const allAnnosDS = {data: [], backgroundColor: []};
        config.data.labels.forEach((tag, idx) => {
            const tag_count = overviewData.all_annotations[tag] || 0;
            const tag_meta = overviewData.tag_metadata[tag] || {}

            const tag_color = getColor(tag_meta.color, idx);

            allAnnosDS.data.push(tag_count);
            allAnnosDS.backgroundColor.push(tag_color);
        });
        allAnnosDS.label = "All Annotations";
        overviewChart.data.datasets.push(allAnnosDS);
    } else {
        overviewChart.data.datasets = [];
        for (const [annotator, annotations] of Object.entries(overviewData.annotations)) {
            const annoDS = {data: [], backgroundColor: []};
            config.data.labels.forEach((tag, idx) => {
                const tag_count = annotations[tag] || 0;
                const tag_meta = overviewData.tag_metadata[tag] || {}
                const tag_color = getColor(tag_meta.color, idx);

                annoDS.data.push(tag_count);
                annoDS.backgroundColor.push(tag_color);
            });

            annoDS.label = annotator; 
            overviewChart.data.datasets.push(annoDS);
        }
    }

    overviewChart.update();
}

function initEditorButton(btn) {
    btn.addEventListener("click", function(evt) {
        const evt_tag = btn.dataset.tag;
        const evt_sample = btn.dataset.sample;
        evt.preventDefault();
        console.log("set-sample", evt_sample, evt_tag);
        const btn_row = btn.closest(".df_inspect_table_row");
        btn_row.style.opacity = 0.5;
        console.log(btn_row);
        console.log(window.location.href);

        const target_uri = window.location.href;
        const req_data = {
            "single_row": evt_sample,
            "set_tag": evt_tag
        }

        fetch(target_uri, {
            method: 'post',
            body: JSON.stringify(req_data)
        }).then(response => {
            return response.text()
        }).then(response => {
            console.log("response", response);
            btn_row.outerHTML = response;

            // make sure events for the new row are bound

            document.querySelectorAll("a.df_inspect_changeaction").forEach(btn => {
                if (evt_sample == btn.dataset.sample) {
                    initEditorButton(btn);
                }
            });
            document.querySelectorAll("button.df_inspect_changeaction").forEach(btn => {
                if (evt_sample == btn.dataset.sample) {
                    initEditorButton(btn);
                }
            });
        });

        return false;
    });
}

function initEditorButtons() {
    document.querySelectorAll("a.df_inspect_changeaction").forEach(initEditorButton);
    document.querySelectorAll("button.df_inspect_changeaction").forEach(initEditorButton);
}

function initWorkpackageFilter(target) {
    target.addEventListener("click", function(evt) {
        if (target.dataset.targethref) {
            const filterform = document.getElementById('form_doquery');
            filterform.action = target.dataset.targethref;
            document.getElementById("restrict_split").value = target.dataset.targetsplit;
            return filterform.submit();
        }
        evt.preventDefault();
        return false;
    });
}
function initWorkpackageFilters() {
    document.querySelectorAll("button.ds_split_filter").forEach(initWorkpackageFilter);
}

function initActionButton(btn) {
    btn.addEventListener("click", function(evt) {
        evt.preventDefault();
        const evt_action = btn.dataset.action;
        const evt_target = btn.dataset.targethref;
        const evt_description = btn.dataset.description || btn.dataset.action || "no description available";

        if (!evt_action) {
            console.error("no action attribute found on", btn);
            return false;
        }

        bootbox.confirm({
            title: "Confirm bulk action?",
            message: "Are you sure you want to continue? This action will " + evt_description,
            buttons: {
                cancel: {
                    label: '<i class="mdi mdi-close"></i> Cancel',
                    className: 'btn-default'
                },
                confirm: {
                    label: '<i class="mdi mdi-check"></i> Confirm',
                    className: 'btn-danger'
                }
            },
            size: "large",
            backdrop: true,
            callback: function (result) {
                if (!result) { return; }
                console.log('triggering bulk action', evt_action);
                const req_data = {
                    "bulk_action": evt_action
                };

                fetch(evt_target, {
                    method: 'post',
                    body: JSON.stringify(req_data)
                }).then(
                    response => response.json()
                ).then(response => {
                    if (response.applied === 0) {
                        response = "The bulk action did not affect any entries."
                    } else {
                        response = "Bulk action was applied to " + response.applied + " entries.";
                        if ((response.affected - response.applied) > 0) {
                            response += " " + (response.affected - response.applied) + " elements remained unchanged (tied votes).";
                        }
                    }

                    bootbox.alert({
                        message: response,
                        size: "small",
                        backdrop: true,
                        callback: function() {
                            window.location.reload();
                        }
                    });
                });
            }
        });
        return false;
    });
}
function initActionButtons() {
    document.querySelectorAll("button.ds_action_btn").forEach(initActionButton);
}

function initAnnotationFilter(target) {
    target.addEventListener("click", function(evt) {
        if (target.dataset.targethref) {
            const filterform = document.getElementById('form_doquery');
            filterform.action = target.dataset.targethref;
            document.getElementById("viewfilter").value = target.dataset.targetviewfilter;
            return filterform.submit();
        }
        evt.preventDefault();
        return false;
    });
}
function initAnnotationFilters() {
    document.querySelectorAll("button.ds_filter").forEach(initAnnotationFilter);
}

function updateTristateTargets() {
    // update target fields

    const includes = [];
    const excludes = [];
    document.querySelectorAll(".cb_show_tag_elem").forEach((cbtn) => {
        const cbtn_state = +cbtn.dataset.tristate || 0;
        if (cbtn_state === 1) {
            includes.push(cbtn.dataset.tag);
        } else if (cbtn_state === 2){
            excludes.push(cbtn.dataset.tag);
        }
    });

    const includeTarget = document.getElementById("restrict_taglist_include");
    const excludeTarget = document.getElementById("restrict_taglist_exclude");
    if (includeTarget && excludeTarget) {
        includeTarget.value = JSON.stringify(includes);
        excludeTarget.value = JSON.stringify(excludes);
        console.log("updated tristate, include:", includes, "exclude:", excludes);
    } else {
        console.log("DOM not ready to update tristate yet");
    }
}

function applyTristate(cbtn) {

    let label_prefix = "";
    switch (+cbtn.dataset.tristate || 0) {
        case 0:
            cbtn.checked = false;
            cbtn.indeterminate = false;
            label_prefix = "";
            break;
        case 1:
            cbtn.checked = true;
            cbtn.indeterminate = false;
            label_prefix = "include";
            break;
        case 2:
            cbtn.checked = false;
            cbtn.indeterminate = true;
            label_prefix = "exclude";
            break;
    }

    // update label with new state
    const btn_tag = cbtn.dataset.tag;
    const cbtn_label = cbtn.parentNode.querySelector("label");
    if (cbtn_label) {
        cbtn_label.textContent = label_prefix + " " + btn_tag;
    }

    updateTristateTargets();
} 

/* function initTagSelect(cbtn) {
    console.log("initTagSelect", cbtn);
    applyTristate(cbtn);

    cbtn.addEventListener("change", (e) => {
        e.preventDefault();
        cbtn.dataset.tristate = ((+cbtn.dataset.tristate) + 1) % 3
        applyTristate(cbtn);
        console.log("change-tristate", cbtn, cbtn.dataset.tristate);
        return document.getElementById("form_doquery").submit();
    });
}

function initTagSelection() {
    document.querySelectorAll(".cb_show_tag_elem").forEach(initTagSelect);
}*/

function initTaskSwitcher() {
    document.querySelectorAll(".inspect_task_switch").forEach((switcher) => {
        switcher.addEventListener("change", (evt) => {
            console.log(evt, evt.target);
            const navigate_target = evt.target.selectedOptions[0]?.dataset?.href;
            if (!navigate_target) { return; }
            window.location.href = navigate_target;
        });
    });
}

document.addEventListener("DOMContentLoaded",function(){
    // initTagSelection();
    initTaskSwitcher();
    initEditorButtons();
    initWorkpackageFilters();
    initActionButtons();
    initAnnotationFilters();
});


