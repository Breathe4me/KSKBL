"""Academic-course scope requested for this Windows edition."""

import re

COURSE_CODE = re.compile(r"(?<![A-Z0-9])[A-Z]{4}\d{4}(?![A-Z0-9])", re.IGNORECASE)


def academic_courses(courses):
    result = []
    for course in courses:
        codes = list(
            dict.fromkeys(
                code.upper()
                for code in COURSE_CODE.findall(
                    str(course.get("course_code", "")) + " " + str(course.get("name", ""))
                )
            )
        )
        if codes:
            result.append(course | {"course_code": " / ".join(codes)})
    return result


def selected_courses(courses, selected_ids):
    return [c for c in academic_courses(courses) if selected_ids is None or c["id"] in selected_ids]
