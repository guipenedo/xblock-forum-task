function ForumTaskXBlock(runtime, element, context) {
    function xblock($, _) {
        let template = _.template($(element).find("#forum_task_tmpl_" + context.xblock_id).text());

        function updateData(){
            if (context.is_course_staff) {
                const load_submissions_url = runtime.handlerUrl(element, 'load_submissions');
                $.get(load_submissions_url, function (data) {
                    render(data);
                });
            } else
                render(context);
        }

        function render(data) {
            let content_el = $(element).find('#forum_task_content_' + context.xblock_id);
            content_el.html(template(data));
            // turmas
            if (data.is_course_cohorted) {
                let turmas_filter = $('#turmas_filter_' + context.xblock_id);
                if (data.cohort)
                    turmas_filter.val(data.cohort)
                turmas_filter.on('change', function () {
                    const change_cohort_handlerurl = runtime.handlerUrl(element, 'change_cohort');
                    context.cohort = this.value;
                    $.post(change_cohort_handlerurl, JSON.stringify({
                        'cohort': this.value
                    }), () => {
                        updateData()
                    });
                });
            }
            if (!context.is_course_staff) {
                $('#submit_tarefa').bind('click', function () {
                    let link = $('#tarefa_link').val()
                    if (!link || !link.startsWith("https://forum.treetree2.school") || !link.startsWith("https://discord.com")){
                        alert("Link inválido...")
                        return
                    }
                    const handlerUrl = runtime.handlerUrl(element, 'submit_link');
                    $.post(handlerUrl, JSON.stringify({
                        'link': link
                    })).done(function (response) {
                        if (response.result === "error")
                            alert(response["message"])
                        else window.location.reload()
                    });
                });
            } else {
                $('.validate-button').bind('click', function () {
                    let user_id = $(this).data("user_id");
                    if (user_id) {
                        const handlerUrl = runtime.handlerUrl(element, 'validate_submission');
                        $.post(handlerUrl, JSON.stringify({
                            'user_id': user_id
                        })).done(function (response) {
                            if (response.result === "error")
                                alert(response["message"])
                            else updateData()
                        });
                    }
                });
            }
        }

        $(function () {
            updateData();
        });
    }

    function loadjs(url) {
        $('<script>')
            .attr('type', 'text/javascript')
            .attr('src', url)
            .appendTo(element);
    }

    if (require === undefined) {
        /**
         * The LMS does not use require.js (although it loads it...) and
         * does not already load jquery.fileupload.  (It looks like it uses
         * jquery.ajaxfileupload instead.  But our XBlock uses
         * jquery.fileupload.
         */
        loadjs('/static/js/vendor/jQuery-File-Upload/js/jquery.iframe-transport.js');
        loadjs('/static/js/vendor/jQuery-File-Upload/js/jquery.fileupload.js');
        xblock($, _);
    } else {
        /**
         * Studio, on the other hand, uses require.js and already knows about
         * jquery.fileupload.
         */
        require(['jquery', 'underscore', 'jquery.fileupload'], xblock);
    }
}
