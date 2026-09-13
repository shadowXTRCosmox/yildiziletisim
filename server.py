import asyncio
import json
import os
import psycopg2
import websockets

# --- VERİTABANI BAĞLANTISI ---
DATABASE_URL = "postgresql://postgres.qbpnqccxvacbgcaioizf:emir8514%2112@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"

conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

# Gerekli tüm tabloları eksiksiz oluşturuyoruz
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT,
        public_key TEXT,
        color TEXT,
        avatar TEXT,
        bio TEXT,
        theme TEXT
    )
""")
cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY,
        sender TEXT,
        target TEXT,
        encrypted_key TEXT,
        nonce TEXT,
        ciphertext TEXT,
        color TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")
cursor.execute("""
    CREATE TABLE IF NOT EXISTS friends (
        user1 TEXT,
        user2 TEXT,
        status TEXT
    )
""")
conn.commit()

connected_clients = {}

async def handler(websocket):
    current_user = None
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "register":
                username = data.get("username")
                password = data.get("password")
                public_key = data.get("public_key")
                color = data.get("color", "#89b4fa")
                avatar = data.get("avatar", "")
                bio = data.get("bio", "")
                theme = data.get("theme", "Mavi Tonları (Varsayılan)")

                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                if cursor.fetchone():
                    await websocket.send(json.dumps({"status": "error", "message": "Bu kullanıcı adı zaten alınmış!"}))
                else:
                    cursor.execute("INSERT INTO users VALUES (%s, %s, %s, %s, %s, %s, %s)", (username, password, public_key, color, avatar, bio, theme))
                    conn.commit()
                    await websocket.send(json.dumps({"status": "success", "message": "Kayıt başarılı!"}))

            elif msg_type == "login":
                username = data.get("username")
                password = data.get("password")

                cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, password))
                user = cursor.fetchone()
                if user:
                    current_user = username
                    connected_clients[current_user] = websocket
                    
                    cursor.execute("SELECT color, avatar, bio, theme FROM users WHERE username = %s", (current_user,))
                    u_data = cursor.fetchone()
                    db_color, db_avatar, db_bio, db_theme = u_data if u_data else ("#89b4fa", "", "", "Mavi Tonları (Varsayılan)")

                    await websocket.send(json.dumps({
                        "status": "success", 
                        "message": "Giriş başarılı",
                        "color": db_color,
                        "avatar": db_avatar,
                        "bio": db_bio,
                        "theme": db_theme
                    }))
                    
                    # Kullanıcı listeleri ve arkadaşlıkları derleyip gönderiyoruz
                    cursor.execute("SELECT username FROM users")
                    users = [row[0] for row in cursor.fetchall()]

                    cursor.execute("SELECT user1, user2 FROM friends WHERE (user1 = %s OR user2 = %s) AND status = 'accepted'", (current_user, current_user))
                    friends = []
                    for u1, u2 in cursor.fetchall():
                        friends.append(u2 if u1 == current_user else u1)

                    cursor.execute("SELECT user1 FROM friends WHERE user2 = %s AND status = 'pending'", (current_user,))
                    requests = [row[0] for row in cursor.fetchall()]

                    cursor.execute("SELECT username, avatar, color, bio FROM users")
                    avatars, colors, bios = {}, {}, {}
                    for u, av, col, bi in cursor.fetchall():
                        avatars[u] = av
                        colors[u] = col
                        bios[u] = bi

                    response = {
                        "type": "user_list_response",
                        "users": users,
                        "friends": friends,
                        "requests": requests,
                        "avatars": avatars,
                        "colors": colors,
                        "bios": bios,
                    }
                    await websocket.send(json.dumps(response))
                else:
                    await websocket.send(json.dumps({"status": "error", "message": "Geçersiz kullanıcı adı veya şifre!"}))

            elif msg_type == "get_users":
                if not current_user: continue
                cursor.execute("SELECT username FROM users")
                users = [row[0] for row in cursor.fetchall()]

                cursor.execute("SELECT user1, user2 FROM friends WHERE (user1 = %s OR user2 = %s) AND status = 'accepted'", (current_user, current_user))
                friends = []
                for u1, u2 in cursor.fetchall():
                    friends.append(u2 if u1 == current_user else u1)

                cursor.execute("SELECT user1 FROM friends WHERE user2 = %s AND status = 'pending'", (current_user,))
                requests = [row[0] for row in cursor.fetchall()]

                cursor.execute("SELECT username, avatar, color, bio FROM users")
                avatars, colors, bios = {}, {}, {}
                for u, av, col, bi in cursor.fetchall():
                    avatars[u] = av
                    colors[u] = col
                    bios[u] = bi

                await websocket.send(json.dumps({
                    "type": "user_list_response", "users": users, "friends": friends, "requests": requests,
                    "avatars": avatars, "colors": colors, "bios": bios
                }))

            elif msg_type == "friend_request":
                target = data.get("target")
                if not current_user or not target:
                    continue

                # Hedef kullanıcının anahtarının (public_key) veritabanında olup olmadığını kontrol ediyoruz
                cursor.execute("SELECT public_key FROM users WHERE username = %s", (target,))
                target_user_data = cursor.fetchone()

                if not target_user_data or not target_user_data[0]:
                    # Anahtar yoksa isteği engelle ve hata mesajı dön
                    await websocket.send(json.dumps({
                        "status": "error",
                        "message": f"'{target}' adlı kullanıcının şifreleme anahtarı bulunamadığı için arkadaşlık isteği gönderilemedi!"
                    }))
                    continue

                # Daha önceden arkadaşlık veya istek var mı kontrolü
                cursor.execute("SELECT * FROM friends WHERE (user1=%s AND user2=%s) OR (user1=%s AND user2=%s)", (current_user, target, target, current_user))
                if not cursor.fetchone():
                    cursor.execute("INSERT INTO friends (user1, user2, status) VALUES (%s, %s, 'pending')", (current_user, target))
                    conn.commit()
                    
                    # Başarılı mesajı gönderene ilet
                    await websocket.send(json.dumps({
                        "status": "success",
                        "message": f"'{target}' adlı kişiye arkadaşlık isteği gönderildi."
                    }))

                    # Eğer hedef kullanıcı çevrimiçiyse anlık bildir
                    if target in connected_clients:
                        await connected_clients[target].send(json.dumps({
                            "type": "friend_request_received", 
                            "sender": current_user
                        }))
                else:
                    await websocket.send(json.dumps({
                        "status": "error",
                        "message": "Bu kullanıcıyla zaten arkadaşsınız veya bekleyen bir isteğiniz var."
                    }))

            elif msg_type == "accept_friend":
                sender = data.get("sender")
                cursor.execute(
                    "UPDATE friends SET status = 'accepted' WHERE user1 = %s AND user2 = %s",
                    (sender, current_user),
                )
                conn.commit()

                # Her iki kullanıcının da arayüzünü güncel listelerle tazeliyoruz
                for u in [current_user, sender]:
                    if u in connected_clients:
                        curr_ws = connected_clients[u]
                        cursor.execute("SELECT username FROM users")
                        users = [row[0] for row in cursor.fetchall()]

                        cursor.execute(
                            "SELECT user1, user2 FROM friends WHERE (user1 = %s OR user2 = %s) AND status = 'accepted'",
                            (u, u),
                        )
                        friends = []
                        for u1, u2 in cursor.fetchall():
                            friends.append(u2 if u1 == u else u1)

                        cursor.execute(
                            "SELECT user1 FROM friends WHERE user2 = %s AND status = 'pending'",
                            (u,),
                        )
                        requests = [row[0] for row in cursor.fetchall()]

                        cursor.execute("SELECT username, avatar, color, bio FROM users")
                        avatars, colors, bios = {}, {}, {}
                        for usr, av, col, bi in cursor.fetchall():
                            avatars[usr] = av
                            colors[usr] = col
                            bios[usr] = bi

                        response = {
                            "type": "user_list_response",
                            "users": users,
                            "friends": friends,
                            "requests": requests,
                            "avatars": avatars,
                            "colors": colors,
                            "bios": bios,
                        }
                        asyncio.create_task(curr_ws.send(json.dumps(response)))

            elif msg_type == "reject_friend":
                sender = data.get("sender")
                cursor.execute("DELETE FROM friends WHERE user1 = %s AND user2 = %s", (sender, current_user))
                conn.commit()

            elif msg_type == "update_profile":
                bio = data.get("bio", "")
                avatar = data.get("avatar", "")
                color = data.get("color", "")
                theme = data.get("theme", "")
                cursor.execute("UPDATE users SET bio=%s, avatar=%s, color=%s, theme=%s WHERE username=%s", (bio, avatar, color, theme, current_user))
                conn.commit()

            elif msg_type == "get_key":
                target = data.get("target")
                cursor.execute("SELECT public_key FROM users WHERE username = %s", (target,))
                res = cursor.fetchone()
                if res:
                    await websocket.send(json.dumps({"type": "key_response", "username": target, "public_key": res[0]}))

            elif msg_type == "msg":
                target = data.get("target")
                sender = current_user
                enc_key = data.get("encrypted_key")
                nonce = data.get("nonce")
                ciphertext = data.get("ciphertext")
                color = data.get("color")

                cursor.execute("INSERT INTO messages (sender, target, encrypted_key, nonce, ciphertext, color) VALUES (%s, %s, %s, %s, %s, %s)", 
                               (sender, target, enc_key, nonce, ciphertext, color))
                conn.commit()

                if target in connected_clients:
                    await connected_clients[target].send(message)

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if current_user and current_user in connected_clients:
            del connected_clients[current_user]

async def main():
    port = int(os.environ.get("PORT", 8765))
    async with websockets.serve(handler, "0.0.0.0", port):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
