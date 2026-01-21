#!/usr/bin/env python3
"""
Script to retroactively fill in player_id and host_id fields in the database
by looking up Discord user IDs from usernames stored in the database.
"""

import os
import asyncio
import asyncpg
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


async def get_username_to_id_mapping(bot):
    """
    Create a mapping of username -> user_id by searching through all guilds the bot is in.
    
    Args:
        bot: The Discord bot instance
        
    Returns:
        Dictionary mapping username (lowercase) -> user_id
    """
    username_to_id = {}
    
    print(f"Bot is in {len(bot.guilds)} guild(s)")
    
    for guild in bot.guilds:
        print(f"Searching guild: {guild.name} ({guild.id})")
        print(f"  Current member count in cache: {len(guild.members)}")
        
        # Fetch all members in the guild
        try:
            # Chunk members to ensure we get all of them (with timeout)
            print(f"  Chunking members (this may take a moment for large guilds)...")
            try:
                await asyncio.wait_for(guild.chunk(), timeout=60.0)
                print(f"  ✅ Finished chunking members")
            except asyncio.TimeoutError:
                print(f"  ⚠️ Chunking timed out after 60 seconds, using cached members")
            except Exception as e:
                print(f"  ⚠️ Error during chunking: {e}, using cached members")
            
            member_count = 0
            processed_count = 0
            for member in guild.members:
                if isinstance(member, discord.Member):
                    # Map username (case-insensitive)
                    if member.name:
                        username_to_id[member.name.lower()] = member.id
                    
                    # Map display_name (case-insensitive)
                    if member.display_name:
                        username_to_id[member.display_name.lower()] = member.id
                    
                    # Map global_name if available (case-insensitive)
                    if member.global_name:
                        username_to_id[member.global_name.lower()] = member.id
                    
                    member_count += 1
                
                processed_count += 1
                # Print progress every 100 members
                if processed_count % 100 == 0:
                    print(f"  Processed {processed_count} members...")
            
            print(f"  ✅ Found {member_count} valid members in {guild.name} (total processed: {processed_count})")
        except Exception as e:
            print(f"  ❌ Error fetching members from {guild.name}: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n✅ Created mapping for {len(username_to_id)} unique usernames")
    return username_to_id


async def ensure_id_columns_exist(db_pool):
    """
    Ensure player_id and host_id columns exist in all tables.
    
    Args:
        db_pool: Database connection pool
    """
    try:
        async with db_pool.acquire() as conn:
            # Add player_id and host_id to reviews table if they don't exist
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='reviews' AND column_name='player_id'
                    ) THEN
                        ALTER TABLE reviews ADD COLUMN player_id BIGINT;
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='reviews' AND column_name='host_id'
                    ) THEN
                        ALTER TABLE reviews ADD COLUMN host_id BIGINT;
                    END IF;
                END $$;
            """)
            
            # Add player_id and host_id to vouches table if they don't exist
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='vouches' AND column_name='player_id'
                    ) THEN
                        ALTER TABLE vouches ADD COLUMN player_id BIGINT;
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='vouches' AND column_name='host_id'
                    ) THEN
                        ALTER TABLE vouches ADD COLUMN host_id BIGINT;
                    END IF;
                END $$;
            """)
            
            # Add player_id and host_id to debts table if they don't exist
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='debts' AND column_name='player_id'
                    ) THEN
                        ALTER TABLE debts ADD COLUMN player_id BIGINT;
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='debts' AND column_name='host_id'
                    ) THEN
                        ALTER TABLE debts ADD COLUMN host_id BIGINT;
                    END IF;
                END $$;
            """)
            
            print("✅ Verified ID columns exist in all tables")
    except Exception as e:
        print(f"❌ Error ensuring columns exist: {e}")
        import traceback
        traceback.print_exc()


async def update_database_ids(db_pool, username_to_id):
    """
    Update player_id and host_id fields in all tables based on username mapping.
    
    Args:
        db_pool: Database connection pool
        username_to_id: Dictionary mapping username (lowercase) -> user_id
    """
    if not db_pool:
        print("❌ Database pool not available")
        return
    
    # First ensure columns exist
    await ensure_id_columns_exist(db_pool)
    
    try:
        async with db_pool.acquire() as conn:
            # Get all unique players and hosts from all tables
            print("\n📊 Fetching all unique players and hosts from database...")
            
            # Get unique players
            player_rows = await conn.fetch("""
                SELECT DISTINCT player FROM reviews
                UNION
                SELECT DISTINCT player FROM vouches
                UNION
                SELECT DISTINCT player FROM debts
            """)
            
            # Get unique hosts
            host_rows = await conn.fetch("""
                SELECT DISTINCT host FROM reviews
                UNION
                SELECT DISTINCT host FROM vouches
                UNION
                SELECT DISTINCT host FROM debts
            """)
            
            print(f"Found {len(player_rows)} unique players and {len(host_rows)} unique hosts")
            
            # Update reviews table
            print("\n🔄 Updating reviews table...")
            reviews_updated = 0
            for row in await conn.fetch("SELECT DISTINCT player FROM reviews WHERE player_id IS NULL"):
                player_username = row['player']
                player_id = username_to_id.get(player_username.lower())
                if player_id:
                    await conn.execute("""
                        UPDATE reviews 
                        SET player_id = $1 
                        WHERE player = $2 AND player_id IS NULL
                    """, player_id, player_username)
                    reviews_updated += 1
            
            for row in await conn.fetch("SELECT DISTINCT host FROM reviews WHERE host_id IS NULL"):
                host_username = row['host']
                host_id = username_to_id.get(host_username.lower())
                if host_id:
                    await conn.execute("""
                        UPDATE reviews 
                        SET host_id = $1 
                        WHERE host = $2 AND host_id IS NULL
                    """, host_id, host_username)
                    reviews_updated += 1
            
            print(f"  Updated {reviews_updated} review entries")
            
            # Update vouches table
            print("\n🔄 Updating vouches table...")
            vouches_updated = 0
            for row in await conn.fetch("SELECT DISTINCT player FROM vouches WHERE player_id IS NULL"):
                player_username = row['player']
                player_id = username_to_id.get(player_username.lower())
                if player_id:
                    await conn.execute("""
                        UPDATE vouches 
                        SET player_id = $1 
                        WHERE player = $2 AND player_id IS NULL
                    """, player_id, player_username)
                    vouches_updated += 1
            
            for row in await conn.fetch("SELECT DISTINCT host FROM vouches WHERE host_id IS NULL"):
                host_username = row['host']
                host_id = username_to_id.get(host_username.lower())
                if host_id:
                    await conn.execute("""
                        UPDATE vouches 
                        SET host_id = $1 
                        WHERE host = $2 AND host_id IS NULL
                    """, host_id, host_username)
                    vouches_updated += 1
            
            print(f"  Updated {vouches_updated} vouch entries")
            
            # Update debts table
            print("\n🔄 Updating debts table...")
            debts_updated = 0
            for row in await conn.fetch("SELECT DISTINCT player FROM debts WHERE player_id IS NULL"):
                player_username = row['player']
                player_id = username_to_id.get(player_username.lower())
                if player_id:
                    await conn.execute("""
                        UPDATE debts 
                        SET player_id = $1 
                        WHERE player = $2 AND player_id IS NULL
                    """, player_id, player_username)
                    debts_updated += 1
            
            for row in await conn.fetch("SELECT DISTINCT host FROM debts WHERE host_id IS NULL"):
                host_username = row['host']
                host_id = username_to_id.get(host_username.lower())
                if host_id:
                    await conn.execute("""
                        UPDATE debts 
                        SET host_id = $1 
                        WHERE host = $2 AND host_id IS NULL
                    """, host_id, host_username)
                    debts_updated += 1
            
            print(f"  Updated {debts_updated} debt entries")
            
            print(f"\n✅ Total updates: {reviews_updated + vouches_updated + debts_updated} entries")
            
    except Exception as e:
        print(f"❌ Error updating database: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Main function to run the ID population script"""
    print("🚀 Starting ID population script...")
    
    # Get Discord bot token
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        print("❌ Error: DISCORD_BOT_TOKEN environment variable not set!")
        return
    
    # Create Discord bot with minimal intents
    intents = discord.Intents.default()
    intents.members = True  # Need members intent to fetch guild members
    
    bot = commands.Bot(command_prefix='!', intents=intents)
    
    # Create database connection pool
    db_pool = None
    
    @bot.event
    async def on_ready():
        nonlocal db_pool
        print(f'✅ Bot logged in as {bot.user}')
        print(f'Bot is in {len(bot.guilds)} guild(s)')
        
        # Connect to database
        try:
            db_pool = await asyncpg.create_pool(
                user=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"),
                host=os.getenv("DB_HOST"),
                port=int(os.getenv("DB_PORT", 5432)),
                database=os.getenv("DB_NAME"),
                min_size=1,
                max_size=10,
                statement_cache_size=0  # Disable prepared statements for pgbouncer
            )
            print("✅ Connected to database")
        except Exception as e:
            print(f"❌ Failed to connect to database: {e}")
            await bot.close()
            return
        
        # Wait a bit for guilds to be ready
        await asyncio.sleep(2)
        
        # Get username to ID mapping
        username_to_id = await get_username_to_id_mapping(bot)
        
        # Update database
        await update_database_ids(db_pool, username_to_id)
        
        # Close database pool
        await db_pool.close()
        print("\n✅ Script completed successfully!")
        
        # Close bot
        await bot.close()
    
    # Run the bot
    try:
        await bot.start(token)
    except KeyboardInterrupt:
        print("\n⚠️ Script interrupted by user")
    except Exception as e:
        print(f"❌ Error running bot: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if db_pool:
            await db_pool.close()


if __name__ == "__main__":
    asyncio.run(main())
