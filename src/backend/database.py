"""
In-memory database configuration and setup for Mergington High School API
"""

import copy
from argon2 import PasswordHasher, exceptions as argon2_exceptions


# ---------------------------------------------------------------------------
# Lightweight in-memory collection that mimics the subset of the PyMongo API
# used by the routers (find, find_one, update_one, aggregate, insert_one,
# count_documents).
# ---------------------------------------------------------------------------

class _UpdateResult:
    """Minimal stand-in for pymongo.results.UpdateResult."""
    def __init__(self, modified_count: int):
        self.modified_count = modified_count


class InMemoryCollection:
    """Dict-backed collection that exposes a PyMongo-compatible interface."""

    def __init__(self):
        self._docs: dict = {}  # keyed by _id

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _matches(doc: dict, query: dict) -> bool:
        """Evaluate a *simple* MongoDB-style query against a document."""
        for key, condition in query.items():
            value = doc
            for part in key.split("."):
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break

            if isinstance(condition, dict):
                for op, operand in condition.items():
                    if op == "$in":
                        if not isinstance(value, list):
                            if value not in operand:
                                return False
                        else:
                            if not any(v in operand for v in value):
                                return False
                    elif op == "$gte":
                        if value is None or value < operand:
                            return False
                    elif op == "$lte":
                        if value is None or value > operand:
                            return False
            else:
                if value != condition:
                    return False
        return True

    # -- public PyMongo-like API ----------------------------------------
    def count_documents(self, filter: dict) -> int:
        if not filter:
            return len(self._docs)
        return sum(1 for d in self._docs.values() if self._matches(d, filter))

    def insert_one(self, document: dict):
        doc = copy.deepcopy(document)
        _id = doc.get("_id")
        self._docs[_id] = doc

    def find_one(self, filter: dict):
        _id = filter.get("_id")
        if _id is not None and len(filter) == 1:
            doc = self._docs.get(_id)
            return copy.deepcopy(doc) if doc else None
        for doc in self._docs.values():
            if self._matches(doc, filter):
                return copy.deepcopy(doc)
        return None

    def find(self, filter: dict | None = None):
        results = []
        for doc in self._docs.values():
            if filter and not self._matches(doc, filter):
                continue
            results.append(copy.deepcopy(doc))
        return results

    def update_one(self, filter: dict, update: dict) -> _UpdateResult:
        doc = None
        _id = filter.get("_id")
        if _id is not None:
            doc = self._docs.get(_id)
        else:
            for d in self._docs.values():
                if self._matches(d, filter):
                    doc = d
                    break
        if doc is None:
            return _UpdateResult(0)

        for op, fields in update.items():
            for field, value in fields.items():
                if op == "$push":
                    doc.setdefault(field, []).append(value)
                elif op == "$pull":
                    lst = doc.get(field, [])
                    if value in lst:
                        lst.remove(value)
                elif op == "$set":
                    doc[field] = value
        return _UpdateResult(1)

    def aggregate(self, pipeline: list):
        """Very minimal aggregation: supports $unwind, $group, $sort."""
        docs = list(copy.deepcopy(d) for d in self._docs.values())
        for stage in pipeline:
            if "$unwind" in stage:
                field = stage["$unwind"].lstrip("$")
                parts = field.split(".")
                new_docs = []
                for doc in docs:
                    value = doc
                    for p in parts:
                        value = value.get(p, []) if isinstance(value, dict) else []
                    if isinstance(value, list):
                        for v in value:
                            d = copy.deepcopy(doc)
                            # set nested value
                            obj = d
                            for p in parts[:-1]:
                                obj = obj[p]
                            obj[parts[-1]] = v
                            new_docs.append(d)
                    else:
                        new_docs.append(doc)
                docs = new_docs
            elif "$group" in stage:
                groups: dict = {}
                group_spec = stage["$group"]
                id_expr = group_spec["_id"]
                if isinstance(id_expr, str) and id_expr.startswith("$"):
                    key_path = id_expr.lstrip("$").split(".")
                else:
                    key_path = None
                for doc in docs:
                    if key_path:
                        val = doc
                        for p in key_path:
                            val = val.get(p) if isinstance(val, dict) else None
                    else:
                        val = id_expr
                    groups[val] = {"_id": val}
                docs = list(groups.values())
            elif "$sort" in stage:
                sort_spec = stage["$sort"]
                for key, direction in reversed(sort_spec.items()):
                    docs.sort(key=lambda d, k=key: d.get(k, ""), reverse=(direction == -1))
        return docs


# Create in-memory collections
activities_collection = InMemoryCollection()
teachers_collection = InMemoryCollection()

# Methods


def hash_password(password):
    """Hash password using Argon2"""
    ph = PasswordHasher()
    return ph.hash(password)


def verify_password(hashed_password: str, plain_password: str) -> bool:
    """Verify a plain password against an Argon2 hashed password.

    Returns True when the password matches, False otherwise.
    """
    ph = PasswordHasher()
    try:
        ph.verify(hashed_password, plain_password)
        return True
    except argon2_exceptions.VerifyMismatchError:
        return False
    except Exception:
        # For any other exception (e.g., invalid hash), treat as non-match
        return False


def init_database():
    """Initialize database if empty"""

    # Initialize activities if empty
    if activities_collection.count_documents({}) == 0:
        for name, details in initial_activities.items():
            activities_collection.insert_one({"_id": name, **details})

    # Initialize teacher accounts if empty
    if teachers_collection.count_documents({}) == 0:
        for teacher in initial_teachers:
            teachers_collection.insert_one(
                {"_id": teacher["username"], **teacher})


# Initial database if empty
initial_activities = {
    "Chess Club": {
        "description": "Learn strategies and compete in chess tournaments",
        "schedule": "Mondays and Fridays, 3:15 PM - 4:45 PM",
        "schedule_details": {
            "days": ["Monday", "Friday"],
            "start_time": "15:15",
            "end_time": "16:45"
        },
        "max_participants": 12,
        "participants": ["michael@mergington.edu", "daniel@mergington.edu"]
    },
    "Programming Class": {
        "description": "Learn programming fundamentals and build software projects",
        "schedule": "Tuesdays and Thursdays, 7:00 AM - 8:00 AM",
        "schedule_details": {
            "days": ["Tuesday", "Thursday"],
            "start_time": "07:00",
            "end_time": "08:00"
        },
        "max_participants": 20,
        "participants": ["emma@mergington.edu", "sophia@mergington.edu"]
    },
    "Morning Fitness": {
        "description": "Early morning physical training and exercises",
        "schedule": "Mondays, Wednesdays, Fridays, 6:30 AM - 7:45 AM",
        "schedule_details": {
            "days": ["Monday", "Wednesday", "Friday"],
            "start_time": "06:30",
            "end_time": "07:45"
        },
        "max_participants": 30,
        "participants": ["john@mergington.edu", "olivia@mergington.edu"]
    },
    "Soccer Team": {
        "description": "Join the school soccer team and compete in matches",
        "schedule": "Tuesdays and Thursdays, 3:30 PM - 5:30 PM",
        "schedule_details": {
            "days": ["Tuesday", "Thursday"],
            "start_time": "15:30",
            "end_time": "17:30"
        },
        "max_participants": 22,
        "participants": ["liam@mergington.edu", "noah@mergington.edu"]
    },
    "Basketball Team": {
        "description": "Practice and compete in basketball tournaments",
        "schedule": "Wednesdays and Fridays, 3:15 PM - 5:00 PM",
        "schedule_details": {
            "days": ["Wednesday", "Friday"],
            "start_time": "15:15",
            "end_time": "17:00"
        },
        "max_participants": 15,
        "participants": ["ava@mergington.edu", "mia@mergington.edu"]
    },
    "Art Club": {
        "description": "Explore various art techniques and create masterpieces",
        "schedule": "Thursdays, 3:15 PM - 5:00 PM",
        "schedule_details": {
            "days": ["Thursday"],
            "start_time": "15:15",
            "end_time": "17:00"
        },
        "max_participants": 15,
        "participants": ["amelia@mergington.edu", "harper@mergington.edu"]
    },
    "Drama Club": {
        "description": "Act, direct, and produce plays and performances",
        "schedule": "Mondays and Wednesdays, 3:30 PM - 5:30 PM",
        "schedule_details": {
            "days": ["Monday", "Wednesday"],
            "start_time": "15:30",
            "end_time": "17:30"
        },
        "max_participants": 20,
        "participants": ["ella@mergington.edu", "scarlett@mergington.edu"]
    },
    "Math Club": {
        "description": "Solve challenging problems and prepare for math competitions",
        "schedule": "Tuesdays, 7:15 AM - 8:00 AM",
        "schedule_details": {
            "days": ["Tuesday"],
            "start_time": "07:15",
            "end_time": "08:00"
        },
        "max_participants": 10,
        "participants": ["james@mergington.edu", "benjamin@mergington.edu"]
    },
    "Debate Team": {
        "description": "Develop public speaking and argumentation skills",
        "schedule": "Fridays, 3:30 PM - 5:30 PM",
        "schedule_details": {
            "days": ["Friday"],
            "start_time": "15:30",
            "end_time": "17:30"
        },
        "max_participants": 12,
        "participants": ["charlotte@mergington.edu", "amelia@mergington.edu"]
    },
    "Weekend Robotics Workshop": {
        "description": "Build and program robots in our state-of-the-art workshop",
        "schedule": "Saturdays, 10:00 AM - 2:00 PM",
        "schedule_details": {
            "days": ["Saturday"],
            "start_time": "10:00",
            "end_time": "14:00"
        },
        "max_participants": 15,
        "participants": ["ethan@mergington.edu", "oliver@mergington.edu"]
    },
    "Science Olympiad": {
        "description": "Weekend science competition preparation for regional and state events",
        "schedule": "Saturdays, 1:00 PM - 4:00 PM",
        "schedule_details": {
            "days": ["Saturday"],
            "start_time": "13:00",
            "end_time": "16:00"
        },
        "max_participants": 18,
        "participants": ["isabella@mergington.edu", "lucas@mergington.edu"]
    },
    "Sunday Chess Tournament": {
        "description": "Weekly tournament for serious chess players with rankings",
        "schedule": "Sundays, 2:00 PM - 5:00 PM",
        "schedule_details": {
            "days": ["Sunday"],
            "start_time": "14:00",
            "end_time": "17:00"
        },
        "max_participants": 16,
        "participants": ["william@mergington.edu", "jacob@mergington.edu"]
    }
}

initial_teachers = [
    {
        "username": "mrodriguez",
        "display_name": "Ms. Rodriguez",
        "password": hash_password("art123"),
        "role": "teacher"
    },
    {
        "username": "mchen",
        "display_name": "Mr. Chen",
        "password": hash_password("chess456"),
        "role": "teacher"
    },
    {
        "username": "principal",
        "display_name": "Principal Martinez",
        "password": hash_password("admin789"),
        "role": "admin"
    }
]
