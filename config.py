import os

BOT_TOKEN = os.environ.get("LEETCODE_BOT_TOKEN", "")
LEETCODE_GRAPHQL_URL = "https://leetcode.com/graphql"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
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
