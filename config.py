import os

BOT_TOKEN = os.environ.get("LEETCODE_BOT_TOKEN", "")
LEETCODE_GRAPHQL_URL = "https://leetcode.com/graphql"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")
PROBLEM_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "problem_cache.json")
SOLUTION_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solution_cache.json")
DEFAULT_TIMEZONE = "Asia/Singapore"
FETCH_DELAY_SECONDS = 1.0

VALID_INTERVALS = {
    "30m": 30 * 60,
    "1h": 60 * 60,
    "2h": 2 * 60 * 60,
    "6h": 6 * 60 * 60,
    "1d": 24 * 60 * 60,
    "off": None,
}

USER_PROFILE_QUERY = """
query getUserProfile($username: String!) {
  matchedUser(username: $username) {
    username
    submitStats: submitStatsGlobal {
      acSubmissionNum {
        difficulty
        count
      }
    }
  }
  recentSubmissionList(username: $username, limit: 50) {
    title
    titleSlug
    timestamp
    statusDisplay
  }
}
"""

PROBLEMS_QUERY = """
query ($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
  problemsetQuestionList: questionList(
    categorySlug: $categorySlug
    limit: $limit
    skip: $skip
    filters: $filters
  ) {
    total: totalNum
    questions: data {
      acRate
      difficulty
      questionFrontendId
      isPaidOnly
      title
      titleSlug
      topicTags {
        name
        slug
      }
    }
  }
}
"""

PROBLEM_DETAIL_QUERY = """
query ($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionId
    questionFrontendId
    title
    titleSlug
    content
    difficulty
    likes
    dislikes
    topicTags {
      name
      slug
    }
    hints
    isPaidOnly
    exampleTestcases
    stats
    codeSnippets {
      lang
      langSlug
      code
    }
  }
}
"""

DAILY_CHALLENGE_QUERY = """
query {
  activeDailyCodingChallengeQuestion {
    date
    link
    question {
      questionFrontendId
      title
      titleSlug
      content
      difficulty
      topicTags {
        name
        slug
      }
      isPaidOnly
      hints
    }
  }
}
"""

GLOBAL_DATA_QUERY = """
query {
  userStatus {
    username
    isSignedIn
  }
}
"""

PROBLEM_STATUS_QUERY = """
query ($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    status
  }
}
"""

RECENT_AC_SUBMISSIONS_QUERY = """
query recentAcSubmissionList($username: String!, $limit: Int!) {
  recentAcSubmissionList(username: $username, limit: $limit) {
    id
    title
    titleSlug
    timestamp
  }
}
"""

STATUS_CODES = {
    10: "Accepted",
    11: "Wrong Answer",
    12: "Memory Limit Exceeded",
    13: "Output Limit Exceeded",
    14: "Time Limit Exceeded",
    15: "Runtime Error",
    20: "Compile Error",
}

LEETCODE_LANG_SLUGS = {
    "python3": "Python3",
    "python": "Python",
    "java": "Java",
    "cpp": "C++",
    "c": "C",
    "csharp": "C#",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "go": "Go",
    "ruby": "Ruby",
    "swift": "Swift",
    "kotlin": "Kotlin",
    "rust": "Rust",
    "scala": "Scala",
    "php": "PHP",
    "dart": "Dart",
    "racket": "Racket",
    "erlang": "Erlang",
    "elixir": "Elixir",
}
