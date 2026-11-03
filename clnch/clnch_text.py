"""Supply application wording to ckit once, before its first use."""

import clnch_strings as strings


def initialize():
    from ckit import ckit_resource

    ckit_resource.setStrings(
        {
            "readonly": strings.CKIT_READONLY,
            "search_found": strings.CKIT_SEARCH_FOUND,
            "search_not_found": strings.CKIT_SEARCH_NOT_FOUND,
            "modified_line_not_found": strings.CKIT_MODIFIED_LINE_NOT_FOUND,
            "bookmark_not_found": strings.CKIT_BOOKMARK_NOT_FOUND,
            "modified_line_or_bookmark_not_found": strings.CKIT_MODIFIED_OR_BOOKMARK_NOT_FOUND,
            "error_config_file_load_failed": strings.CKIT_CONFIG_LOAD_ERROR,
            "error_config_file_exec_failed": strings.CKIT_CONFIG_EXEC_ERROR,
            "invalid_key": strings.CKIT_INVALID_KEY,
            "color_not_found": strings.CKIT_COLOR_NOT_FOUND,
            "job_suspended": strings.CKIT_JOB_SUSPENDED,
            "job_resumed": strings.CKIT_JOB_RESUMED,
        }
    )
