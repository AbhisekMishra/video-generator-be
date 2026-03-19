"""
Simple Python Examples for Beginners

This file demonstrates the key Python concepts used in this project
with simple, easy-to-understand examples.

Run this file with: python SIMPLE_EXAMPLES.py
"""

import asyncio
import json
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


# ============================================================================
# 1. TYPE HINTS (Python's TypeScript)
# ============================================================================

def greet(name: str) -> str:
    """
    Type hints tell you what type each parameter and return value should be.

    JavaScript equivalent:
    function greet(name: string): string
    """
    return f"Hello, {name}!"


# Optional means the value can be None (like null in JavaScript)
def find_user(user_id: int) -> Optional[str]:
    """
    Returns a user name or None if not found.

    JavaScript equivalent:
    function findUser(userId: number): string | null
    """
    users = {1: "Alice", 2: "Bob"}
    return users.get(user_id)  # Returns None if key not found


# List[str] is like string[] in TypeScript
def get_tags() -> List[str]:
    """Returns a list of strings."""
    return ["python", "tutorial", "beginner"]


# Dict is like an object/map
def get_user_data() -> Dict[str, Any]:
    """
    Returns a dictionary (object) with string keys and any type of value.

    JavaScript equivalent:
    function getUserData(): { [key: string]: any }
    """
    return {
        "name": "Alice",
        "age": 30,
        "hobbies": ["coding", "reading"]
    }


# ============================================================================
# 2. PYDANTIC MODELS (Runtime Validation)
# ============================================================================

class User(BaseModel):
    """
    Pydantic automatically validates data at runtime.

    Similar to Zod in JavaScript:
    const UserSchema = z.object({
        name: z.string(),
        age: z.number(),
        email: z.string().optional()
    })
    """
    name: str
    age: int
    email: Optional[str] = None  # Default value is None


def create_user_example():
    """Demonstrate Pydantic validation."""

    # Valid data - this works
    user1 = User(name="Alice", age=30)
    print(f"✅ Created user: {user1.name}, age {user1.age}")

    # Pydantic auto-converts compatible types
    user2 = User(name="Bob", age="25")  # String "25" auto-converts to int 25
    print(f"✅ Created user: {user2.name}, age {user2.age} (auto-converted)")

    # Invalid data - this raises an error
    try:
        user3 = User(name="Charlie", age="invalid")  # Can't convert to int
    except Exception as e:
        print(f"❌ Validation failed: {e}")


# ============================================================================
# 3. ASYNC/AWAIT (Same as JavaScript!)
# ============================================================================

async def fetch_data(url: str) -> Dict:
    """
    Async function - must be called with await.

    JavaScript equivalent:
    async function fetchData(url: string): Promise<object>
    """
    print(f"📡 Fetching data from {url}...")

    # Simulate network delay
    await asyncio.sleep(1)  # Like await new Promise(resolve => setTimeout(resolve, 1000))

    return {"status": "success", "data": [1, 2, 3]}


async def async_example():
    """Demonstrate async/await."""
    print("\n=== Async Example ===")

    # Call async function with await
    result = await fetch_data("https://api.example.com")
    print(f"✅ Got result: {result}")


# ============================================================================
# 4. DICTIONARIES (Objects in JavaScript)
# ============================================================================

def dictionary_example():
    """Demonstrate dictionary operations."""
    print("\n=== Dictionary Example ===")

    # Create dictionary (like { } in JavaScript)
    person = {
        "name": "Alice",
        "age": 30,
        "city": "New York"
    }

    # Access values with brackets (not dot notation!)
    print(f"Name: {person['name']}")

    # Get with default value (returns None if key not found)
    email = person.get("email", "no-email@example.com")
    print(f"Email: {email}")

    # Add new key
    person["job"] = "Engineer"

    # Check if key exists
    if "age" in person:
        print(f"Age exists: {person['age']}")

    # Loop through dictionary
    print("\nAll keys and values:")
    for key, value in person.items():
        print(f"  {key}: {value}")


# ============================================================================
# 5. LISTS (Arrays in JavaScript)
# ============================================================================

def list_example():
    """Demonstrate list operations."""
    print("\n=== List Example ===")

    # Create list (like [] in JavaScript)
    numbers = [1, 2, 3, 4, 5]

    # Append (like push in JavaScript)
    numbers.append(6)
    print(f"After append: {numbers}")

    # List comprehension (like map in JavaScript)
    # JavaScript: numbers.map(n => n * 2)
    doubled = [n * 2 for n in numbers]
    print(f"Doubled: {doubled}")

    # Filter (like filter in JavaScript)
    # JavaScript: numbers.filter(n => n > 3)
    filtered = [n for n in numbers if n > 3]
    print(f"Filtered (>3): {filtered}")

    # Length (like .length in JavaScript)
    print(f"Length: {len(numbers)}")

    # Access by index
    print(f"First item: {numbers[0]}")
    print(f"Last item: {numbers[-1]}")  # Negative index counts from end!


# ============================================================================
# 6. F-STRINGS (Template Literals)
# ============================================================================

def string_example():
    """Demonstrate f-strings."""
    print("\n=== String Example ===")

    name = "Alice"
    age = 30

    # f-string (like template literal in JavaScript)
    # JavaScript: `Hello, ${name}! You are ${age} years old.`
    message = f"Hello, {name}! You are {age} years old."
    print(message)

    # Can include expressions
    message2 = f"Next year you'll be {age + 1}"
    print(message2)

    # Multi-line strings with triple quotes
    long_text = """
    This is a multi-line string.
    You can write multiple lines.
    No need for \n or template literals!
    """
    print(long_text)


# ============================================================================
# 7. ERROR HANDLING (try/except)
# ============================================================================

def error_handling_example():
    """Demonstrate error handling."""
    print("\n=== Error Handling Example ===")

    try:
        # Try to divide by zero
        result = 10 / 0
    except ZeroDivisionError as e:
        # Catch specific error type
        print(f"❌ Caught division error: {e}")
    except Exception as e:
        # Catch any other error
        print(f"❌ Caught general error: {e}")
    finally:
        # Always runs (cleanup code)
        print("✅ Cleanup complete")


# ============================================================================
# 8. WITH STATEMENT (Context Manager)
# ============================================================================

def file_example():
    """Demonstrate file operations with 'with'."""
    print("\n=== File Example ===")

    # Write to file
    with open("example.txt", "w") as f:
        f.write("Hello, World!\n")
        f.write("This is a test file.")
    # File is automatically closed here!

    # Read from file
    with open("example.txt", "r") as f:
        content = f.read()
        print(f"File content:\n{content}")

    # Clean up
    import os
    os.remove("example.txt")
    print("✅ File cleaned up")


# ============================================================================
# 9. JSON OPERATIONS
# ============================================================================

def json_example():
    """Demonstrate JSON operations."""
    print("\n=== JSON Example ===")

    # Python dictionary
    data = {
        "name": "Alice",
        "age": 30,
        "hobbies": ["coding", "reading"]
    }

    # Convert to JSON string (like JSON.stringify in JavaScript)
    json_string = json.dumps(data, indent=2)
    print(f"JSON string:\n{json_string}")

    # Parse JSON string (like JSON.parse in JavaScript)
    parsed_data = json.loads(json_string)
    print(f"\nParsed data: {parsed_data}")


# ============================================================================
# 10. FUNCTION THAT RETURNS DICTIONARY (Common Pattern)
# ============================================================================

def process_data(input_value: str) -> Dict[str, Any]:
    """
    This pattern is used throughout the workflow nodes.

    Each node receives state, processes it, and returns a dictionary
    of updates to merge into the state.
    """
    print(f"\n=== Processing: {input_value} ===")

    # Do some processing
    result = input_value.upper()
    word_count = len(input_value.split())

    # Return updates as a dictionary
    return {
        "processed_text": result,
        "word_count": word_count,
        "status": "completed"
    }


# ============================================================================
# MAIN FUNCTION - Run all examples
# ============================================================================

async def main():
    """Run all examples."""
    print("=" * 80)
    print("Python Beginner Examples")
    print("=" * 80)

    # Type hints
    message = greet("Alice")
    print(f"\n✅ Greeting: {message}")

    user = find_user(1)
    print(f"✅ Found user: {user}")

    tags = get_tags()
    print(f"✅ Tags: {tags}")

    # Pydantic
    create_user_example()

    # Async/await
    await async_example()

    # Dictionaries
    dictionary_example()

    # Lists
    list_example()

    # Strings
    string_example()

    # Error handling
    error_handling_example()

    # Files
    file_example()

    # JSON
    json_example()

    # Dictionary return pattern
    updates = process_data("hello world from python")
    print(f"\n✅ Updates returned: {json.dumps(updates, indent=2)}")

    print("\n" + "=" * 80)
    print("✅ All examples completed!")
    print("=" * 80)


# ============================================================================
# Run the examples
# ============================================================================

if __name__ == "__main__":
    # This runs only when you execute this file directly
    # (not when importing it as a module)

    # Run async main function
    # This is the entry point for async code in Python
    asyncio.run(main())
