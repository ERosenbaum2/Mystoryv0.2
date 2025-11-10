"""
Script to load initial pre-vetted stories into the database.

This script performs a one-time import of the two required stories:
- "Little Red Riding Hood" (girl)
- "Jack and the Beanstalk" (boy)

Run this script once to seed the database with initial story data.
"""

import os
import sys
from project import app, init_db
from models import db, Storyline

# Story data based on STORYBOOK_PROMPTS from project.py
STORY_DATA = {
    'red': {
        'name': 'Little Red Riding Hood',
        'gender': 'girl',
        'pages': [
            {
                'scene_desc': 'Child as Little Red Riding Hood with basket, talking to mother',
                'text': 'Once upon a time, there was a little girl who loved to visit her grandmother. Her mother packed a basket with treats.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo is dressed as Little Red Riding Hood, wearing a red hooded cape, holding a wicker basket filled with bread, cakes, and a bottle of wine. The child is standing in a cozy kitchen, talking to their mother who is packing the basket. The mother has a warm, loving expression. The scene is bright, cheerful, and suitable for children, with warm colors and a homey atmosphere.'
            },
            {
                'scene_desc': 'Child walking through the magical forest',
                'text': 'The little girl put on her red hooded cape and set off through the forest. The path was lined with beautiful flowers.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo, dressed in a red hooded cape and carrying a basket, is walking through a beautiful, enchanted forest. Sunlight filters through tall trees, flowers line the path, and friendly woodland creatures (birds, rabbits, squirrels) peek out curiously. The child looks happy and brave, following a winding path. The illustration is colorful, magical, and age-appropriate for children.'
            },
            {
                'scene_desc': 'Child meeting the wolf in the forest',
                'text': 'As she walked along, a friendly wolf appeared on the path. The wolf looked curious and asked where she was going.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo, dressed as Little Red Riding Hood, encounters a friendly-looking wolf in the forest. The wolf is sitting on the path ahead, appearing curious but not scary. The child looks surprised but not frightened. The forest setting is still beautiful and magical, with butterflies and flowers nearby. The scene is portrayed in a gentle, non-threatening way suitable for children.'
            },
            {
                'scene_desc': 'Child conversing with the wolf about visiting grandmother',
                'text': 'The little girl told the wolf she was visiting her grandmother. The wolf seemed very interested in her journey.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo, as Little Red Riding Hood, is having a conversation with the friendly wolf on the forest path. The wolf is asking where the child is going, and the child is pointing ahead, explaining they are visiting their grandmother. The wolf looks curious and interested. The scene is friendly and conversational, with the beautiful forest as the backdrop. The illustration maintains a warm, innocent tone.'
            },
            {
                'scene_desc': 'Wolf running ahead to grandmother\'s cottage',
                'text': 'The wolf said goodbye and ran ahead on the path. The little girl continued walking slowly, picking flowers along the way.',
                'image_prompt_template': 'Create a children\'s book illustration page. The wolf is running ahead on the forest path, moving quickly but not appearing scary, just excited. The child from the photo, as Little Red Riding Hood, is shown in the background, still walking slowly and picking flowers. The wolf is heading toward a cottage in the distance. The scene shows the forest path with flowers and sunlight, maintaining a gentle, storybook quality.'
            },
            {
                'scene_desc': 'Child arriving at grandmother\'s cottage',
                'text': 'Finally, the little girl arrived at her grandmother\'s cozy cottage. The cottage had a beautiful flower garden and a welcoming door.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo, as Little Red Riding Hood, arrives at a charming cottage in the forest. The cottage has a thatched roof, a flower garden, and a welcoming door. The child is approaching the door, holding the basket, ready to visit their grandmother. The scene is warm and inviting, with soft afternoon light and a cozy, safe feeling.'
            },
            {
                'scene_desc': 'Child knocking on grandmother\'s door',
                'text': 'The little girl knocked on the door. She was excited to see her grandmother and share the treats from her basket.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo, as Little Red Riding Hood, is knocking on grandmother\'s cottage door. The child looks cheerful and expectant, holding the basket. The cottage door is slightly ajar, which adds a touch of mystery. The scene is still warm and inviting, with flowers around the door and gentle forest light. The illustration maintains a child-friendly atmosphere.'
            },
            {
                'scene_desc': 'Child discovers the wolf in grandmother\'s bed',
                'text': 'When she entered, the little girl saw someone in grandmother\'s bed. But something looked different about grandmother today.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo, as Little Red Riding Hood, is inside grandmother\'s cottage, standing by a bed. In the bed is a friendly-looking wolf wearing a nightcap and glasses, pretending to be the grandmother. The child looks curious and slightly confused but not scared. The room is cozy and warm, with floral wallpaper and a fireplace. The illustration maintains a gentle, humorous tone suitable for children.'
            },
            {
                'scene_desc': 'Child noticing something different about grandmother',
                'text': 'The little girl noticed that grandmother\'s eyes, ears, and teeth looked much bigger than usual. She felt curious and thoughtful.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo, as Little Red Riding Hood, is noticing something unusual about "grandmother" - pointing out that the eyes, ears, and teeth look bigger than usual. The child is sitting on the edge of the bed, looking curious and thoughtful. The wolf in the bed looks friendly and comical. The scene is humorous and gentle, showing the child\'s cleverness in a non-scary way.'
            },
            {
                'scene_desc': 'Child realizing something is wrong and calling for help',
                'text': 'Suddenly, the little girl realized something was wrong. She called out for help, feeling brave and determined.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo, as Little Red Riding Hood, has realized something is wrong and is calling out for help or about to run. The child looks surprised but not terrified, maintaining a brave expression. The wolf in the bed is still looking friendly and comical. The scene shows a moment of realization but keeps a light, humorous tone suitable for children.'
            },
            {
                'scene_desc': 'Hunter rescues child and grandmother',
                'text': 'A kind hunter heard the call and came to help. The hunter rescued the little girl and found the real grandmother safe.',
                'image_prompt_template': 'Create a children\'s book illustration page. A kind, brave hunter character enters grandmother\'s cottage and rescues the child and the real grandmother (who was hiding in the closet). The child from the photo, still dressed as Little Red Riding Hood, is being hugged by their grandmother, both looking happy and relieved. The wolf has run away, and the hunter is standing protectively nearby. The scene is joyful and safe, with warm colors and a happy resolution.'
            },
            {
                'scene_desc': 'Happy ending with family together',
                'text': 'Everyone was safe and happy. The little girl, her grandmother, and her mother all sat together, sharing tea and treats.',
                'image_prompt_template': 'Create a children\'s book illustration page. The happy ending scene shows the child from the photo (as Little Red Riding Hood), their grandmother, and the mother all sitting together in grandmother\'s cozy cottage, sharing tea and the treats from the basket. Everyone is smiling and happy. The cottage is warm and inviting, with flowers in vases and afternoon sunlight streaming through the windows. The illustration radiates love, family, and safety.'
            }
        ]
    },
    'jack': {
        'name': 'Jack and the Beanstalk',
        'gender': 'boy',
        'pages': [
            {
                'scene_desc': 'Child as Jack with mother and the cow at home',
                'text': 'Once upon a time, there was a boy named Jack who lived with his mother. They had a cow, but they needed money.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo is dressed as Jack, wearing simple peasant clothes, standing in a humble cottage with their mother. The mother looks sad and worried, and there\'s a cow in the background. The child, as Jack, is holding the cow\'s rope, looking determined to help. The cottage interior is cozy but shows they need money. The scene is warm and loving, showing the bond between mother and child.'
            },
            {
                'scene_desc': 'Child trading the cow for magic beans',
                'text': 'Jack took the cow to the market to sell it. An old merchant offered him magic beans in exchange for the cow.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo, dressed as Jack, is standing in a village marketplace, trading their family cow for a handful of colorful, glowing magic beans. An old, mysterious merchant with a twinkle in their eye is handing over the beans. The child looks hopeful and excited, holding out their hand to receive the magical beans. The marketplace is bustling but the focus is on this magical exchange.'
            },
            {
                'scene_desc': 'Mother\'s reaction - throwing the beans away',
                'text': 'When Jack returned home, his mother was upset. She threw the magic beans out the window, thinking they were worthless.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo, as Jack, has returned home and is showing the magic beans to their mother. The mother looks disappointed and upset, throwing the beans out the window. The child looks sad but hopeful. The cottage interior shows their humble life. The scene captures the mother\'s frustration but also shows the love between them. The illustration is warm and emotional but not scary.'
            },
            {
                'scene_desc': 'The magical beanstalk growing overnight',
                'text': 'The next morning, Jack woke up to an amazing sight. A giant beanstalk had grown overnight, reaching high into the clouds.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo, as Jack, is standing outside their cottage in the morning, looking up in amazement at an enormous, magical beanstalk that grew overnight. The beanstalk reaches high into the sky, through fluffy white clouds. The child\'s face shows wonder and excitement. The mother is also visible, looking surprised but amazed. The scene is bright and magical, with morning sunlight and a sense of adventure beginning.'
            },
            {
                'scene_desc': 'Child climbing the giant beanstalk',
                'text': 'Jack decided to climb the beanstalk. He climbed higher and higher, past giant green leaves and magical sparkles.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo, as Jack, is climbing the enormous beanstalk. They are about halfway up, looking determined and brave. Giant green leaves surround them, and they can see the ground getting smaller below. The beanstalk is covered in magical sparkles and the sky above shows fluffy clouds. The illustration captures the excitement and adventure of the climb.'
            },
            {
                'scene_desc': 'Child discovering the giant\'s castle in the clouds',
                'text': 'At the top, Jack discovered a magnificent castle in the clouds. The castle was made of gold and looked amazing.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo, as Jack, has reached the top of the beanstalk and is standing in a magnificent castle in the clouds. The castle is made of gold and has beautiful architecture. The child is peeking through a window or door, looking amazed at the sight of a friendly-looking giant (not scary, but large and interesting) inside. The scene is magical and wondrous, with clouds floating by.'
            },
            {
                'scene_desc': 'Child finding the golden treasure',
                'text': 'Inside the castle, Jack found a golden egg and a bag of gold coins. He picked them up, feeling clever and happy.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo, as Jack, is inside the giant\'s castle, holding a golden, glowing egg or a small bag of gold coins. The child looks clever and happy, having found treasure. The giant is in the background, perhaps sleeping or looking the other way. The castle interior is magnificent with golden details. The scene shows the child being brave and resourceful.'
            },
            {
                'scene_desc': 'Giant noticing Jack in the castle',
                'text': 'The friendly giant woke up and noticed Jack. The giant looked surprised and curious, but not angry or scary.',
                'image_prompt_template': 'Create a children\'s book illustration page. The friendly giant in the castle has woken up and noticed the child from the photo (as Jack). The giant looks surprised and curious, but not angry or scary. The child is holding the treasure, looking a bit startled but not terrified. The scene is portrayed in a gentle, friendly way, with the giant appearing more like a large, curious character than a threat.'
            },
            {
                'scene_desc': 'Child hiding from the giant in the castle',
                'text': 'Jack quickly hid behind a golden chair. He was clever and quick-thinking, holding onto the treasure safely.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo, as Jack, is hiding cleverly in the giant\'s castle - perhaps behind a large golden chair or inside a cupboard - while the friendly giant looks around curiously. The child is holding the treasure and looks resourceful and quick-thinking. The castle interior is magnificent. The scene shows the child\'s cleverness in a fun, adventurous way.'
            },
            {
                'scene_desc': 'Child climbing down with the treasure, giant following',
                'text': 'Jack climbed down the beanstalk as fast as he could. The friendly giant followed, but Jack was determined to get home.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo, as Jack, is quickly climbing down the beanstalk, holding the golden treasure. They look determined and focused, moving quickly. The friendly giant is at the top of the beanstalk, looking down curiously but not angry. The mother is visible at the bottom, looking up with concern and hope. The scene shows action and adventure, but in a child-friendly way.'
            },
            {
                'scene_desc': 'Child preparing to cut down the beanstalk',
                'text': 'When Jack reached the bottom, he called to his mother for an axe. He was determined to protect his family.',
                'image_prompt_template': 'Create a children\'s book illustration page. The child from the photo, as Jack, has reached the bottom of the beanstalk and is calling to their mother to bring an axe. The child looks determined and brave. The mother is running to help. In the background, the friendly giant is starting to climb down the beanstalk. The scene shows the child taking action to protect their family, showing courage and quick thinking.'
            },
            {
                'scene_desc': 'Happy ending with child and mother, now wealthy and safe',
                'text': 'Jack and his mother cut down the beanstalk and were safe. They now had the golden treasure and lived happily ever after.',
                'image_prompt_template': 'Create a children\'s book illustration page. The happy ending scene shows the child from the photo (as Jack) and their mother together in their cozy cottage, now filled with the golden treasure. The beanstalk has been cut down, and they are safe. The mother is hugging the child, both looking happy and relieved. The cottage is now more comfortable, with the golden egg or coins visible. The scene radiates joy, love, and the reward for being brave and clever. The illustration is warm and celebratory.'
            }
        ]
    }
}


def load_stories():
    """
    Load initial story data into the database.
    This function creates or updates the two required stories.
    """
    with app.app_context():
        # Ensure database tables exist
        db.create_all()
        
        stories_loaded = 0
        stories_updated = 0
        
        for story_id, story_info in STORY_DATA.items():
            # Check if story already exists
            existing_story = Storyline.query.filter_by(story_id=story_id).first()
            
            if existing_story:
                # Update existing story
                existing_story.name = story_info['name']
                existing_story.gender = story_info['gender']
                existing_story.set_pages(story_info['pages'])
                stories_updated += 1
                print(f"✓ Updated story: {story_info['name']} ({story_info['gender']})")
            else:
                # Create new story
                new_story = Storyline(
                    story_id=story_id,
                    name=story_info['name'],
                    gender=story_info['gender']
                )
                new_story.set_pages(story_info['pages'])
                db.session.add(new_story)
                stories_loaded += 1
                print(f"✓ Loaded story: {story_info['name']} ({story_info['gender']})")
        
        # Commit all changes
        try:
            db.session.commit()
            print(f"\n✅ Successfully loaded {stories_loaded} new stories and updated {stories_updated} existing stories.")
            print(f"📚 Total stories in database: {Storyline.query.count()}")
            
            # Display summary
            print("\n📖 Stories in database:")
            for story in Storyline.query.all():
                pages = story.get_pages()
                print(f"   - {story.name} ({story.gender}): {len(pages)} pages")
            
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Error loading stories: {str(e)}")
            raise


if __name__ == '__main__':
    print("🚀 Starting story data import...")
    print("=" * 50)
    
    try:
        load_stories()
        print("\n" + "=" * 50)
        print("✨ Story import completed successfully!")
    except Exception as e:
        print("\n" + "=" * 50)
        print(f"❌ Story import failed: {str(e)}")
        sys.exit(1)

