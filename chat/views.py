import os
import secrets

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import services


def root_redirect(request):
    return redirect('index_php')


def require_login(request):
    return request.session.get('user_id') is not None


def _redirect_index_conversation(conversation_id=None):
    url = reverse('index_php')
    if conversation_id:
        return f'{url}?conversation_id={int(conversation_id)}'
    return url


def _chat_csrf(request):
    token = request.session.get('chat_csrf_token')
    if not token:
        token = secrets.token_hex(32)
        request.session['chat_csrf_token'] = token
    return token


def _session_role_for_user(user):
    return 'super_admin' if services.is_user_super_admin(int(user['id'])) else str(user.get('role') or 'user')


@require_http_methods(['GET', 'POST'])
def login_view(request):
    if require_login(request):
        return redirect('index_php')

    context = {'title': 'Connexion', 'error': ''}
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        if not username or not password:
            context['error'] = 'Identifiants requis.'
        else:
            ok, err, user = services.login_user(username, password)
            if ok:
                request.session['user_id'] = int(user['id'])
                request.session['username'] = user['username']
                request.session['role'] = _session_role_for_user(user)
                return redirect('index_php')
            context['error'] = err
    return render(request, 'chat/login.html', context)


@require_http_methods(['GET', 'POST'])
def register_view(request):
    if require_login(request):
        return redirect('index_php')

    context = {'title': 'Inscription', 'error': ''}
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        confirm = request.POST.get('confirm_password') or ''

        if not username or not password:
            context['error'] = "Nom d'utilisateur et mot de passe obligatoires."
        elif password != confirm:
            context['error'] = 'Les mots de passe ne correspondent pas.'
        elif len(password) < 6:
            context['error'] = 'Mot de passe trop court (minimum 6 caracteres).'
        else:
            ok, err = services.register_user(username, password)
            if not ok:
                context['error'] = err
            else:
                ok2, err2, user = services.login_user(username, password)
                if ok2:
                    request.session['user_id'] = int(user['id'])
                    request.session['username'] = user['username']
                    request.session['role'] = _session_role_for_user(user)
                    return redirect('index_php')
                context['error'] = err2 or 'Compte cree, mais connexion automatique impossible.'

    return render(request, 'chat/register.html', context)


@require_http_methods(['GET', 'POST'])
def logout_view(request):
    for key in ('user_id', 'username', 'role', 'chat_csrf_token', 'admin_csrf_token'):
        if key in request.session:
            del request.session[key]

    request.session.flush()

    response = redirect('login_php')
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path='/')
    return response


@require_http_methods(['GET', 'POST'])
def index_view(request):
    if not require_login(request):
        return redirect('login_php')

    user_id = int(request.session['user_id'])
    moderation_reason = services.moderation_message(services.get_user_by_id(user_id))
    is_restricted = moderation_reason is not None

    if request.method == 'POST' and request.POST.get('create_inbox') == '1':
        if is_restricted:
            messages.error(request, moderation_reason)
            return redirect('index_php')

        target_user_id = int(request.POST.get('target_user_id') or 0)
        cid = services.get_or_create_direct_conversation(user_id, target_user_id)
        if cid > 0:
            return redirect(_redirect_index_conversation(cid))

        messages.error(request, 'Impossible de creer cette conversation privee.')
        return redirect('index_php')

    requested_cid = int(request.GET.get('conversation_id') or 0)
    conversations = services.get_user_conversations(user_id)
    if not conversations:
        services.ensure_general_conversation_id()
        conversations = services.get_user_conversations(user_id)

    active = services.get_conversation_for_user(requested_cid, user_id) if requested_cid > 0 else None
    if not active and conversations:
        active = services.get_conversation_for_user(conversations[0]['id'], user_id)

    active_id = int(active['id']) if active else services.ensure_general_conversation_id()
    if not active:
        active = {'id': active_id, 'display_name': 'Général', 'type': 'group'}

    context = {
        'title': 'JemiChat',
        'conversations': conversations,
        'active_conversation': active,
        'active_conversation_id': active_id,
        'chat_messages': list(reversed(services.get_conversation_messages(active_id, 100))),
        'inbox_candidates': services.get_inbox_candidates(user_id),
        'online_count': len(services.get_online_users()),
        'is_restricted': is_restricted,
        'moderation_reason': moderation_reason,
        'chat_csrf_token': _chat_csrf(request),
        'emojis': [
            '😀', '😂', '😍', '🥰', '😎', '🤔', '😢', '😡', '👍', '👏',
            '🙏', '❤️', '🔥', '🎉', '🤝', '✅', '💡', '🚀', '📌', '👀',
        ],
    }
    return render(request, 'chat/index.html', context)


@require_POST
def send_message_view(request):
    if not require_login(request):
        return redirect('login_php')

    user_id = int(request.session['user_id'])
    moderation_reason = services.moderation_message(services.get_user_by_id(user_id))
    if moderation_reason:
        messages.error(request, moderation_reason)
        return redirect('index_php')

    message_text = (request.POST.get('message') or '').strip()
    conversation_id = int(request.POST.get('conversation_id') or services.ensure_general_conversation_id())
    conv = services.get_conversation_for_user(conversation_id, user_id)
    if not conv:
        messages.error(request, 'Conversation invalide.')
        return redirect('index_php')

    redirect_url = _redirect_index_conversation(conversation_id)
    file_obj = request.FILES.get('file')
    if not file_obj and not message_text:
        return redirect(redirect_url)

    try:
        file_meta = services.save_upload(file_obj) if file_obj else None
        services.insert_message(
            user_id=user_id,
            conversation_id=conversation_id,
            message=message_text,
            file_meta=file_meta,
            ephemeral_week=request.POST.get('ephemeral_week') == '1',
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    except Exception:
        messages.error(request, "Impossible d'envoyer le message.")

    return redirect(redirect_url)


@require_POST
def edit_message_view(request):
    if not require_login(request):
        return redirect('login_php')

    user_id = int(request.session['user_id'])
    message_id = int(request.POST.get('message_id') or 0)
    conversation_id = int(request.POST.get('conversation_id') or 0)
    new_message = (request.POST.get('message') or '').strip()
    redirect_url = _redirect_index_conversation(conversation_id)

    token = request.POST.get('chat_csrf_token') or ''
    if token != request.session.get('chat_csrf_token', ''):
        messages.error(request, 'Session expiree. Reessayez.')
        return redirect(redirect_url)

    if message_id <= 0 or conversation_id <= 0 or not new_message:
        messages.error(request, 'Donnees invalides pour la modification du message.')
        return redirect(redirect_url)

    conv = services.get_conversation_for_user(conversation_id, user_id)
    if not conv:
        messages.error(request, 'Conversation invalide.')
        return redirect('index_php')

    if services.update_own_message(message_id, conversation_id, user_id, new_message):
        messages.success(request, 'Message modifie.')
    else:
        messages.error(request, 'Impossible de modifier ce message.')

    return redirect(redirect_url)


@require_POST
def delete_message_view(request):
    if not require_login(request):
        return redirect('login_php')

    user_id = int(request.session['user_id'])
    message_id = int(request.POST.get('message_id') or 0)
    conversation_id = int(request.POST.get('conversation_id') or 0)
    redirect_url = _redirect_index_conversation(conversation_id)

    token = request.POST.get('chat_csrf_token') or ''
    if token != request.session.get('chat_csrf_token', ''):
        messages.error(request, 'Session expiree. Reessayez.')
        return redirect(redirect_url)

    if message_id <= 0 or conversation_id <= 0:
        messages.error(request, 'Donnees invalides pour la suppression du message.')
        return redirect(redirect_url)

    conv = services.get_conversation_for_user(conversation_id, user_id)
    if not conv:
        messages.error(request, 'Conversation invalide.')
        return redirect('index_php')

    if services.delete_own_message(message_id, conversation_id, user_id):
        messages.success(request, 'Message supprime.')
    else:
        messages.error(request, 'Impossible de supprimer ce message.')

    return redirect(redirect_url)


@require_POST
def upload_view(request):
    if not require_login(request):
        return redirect('login_php')

    user_id = int(request.session['user_id'])
    file_obj = request.FILES.get('file')
    conversation_id = int(request.POST.get('conversation_id') or services.ensure_general_conversation_id())
    redirect_url = _redirect_index_conversation(conversation_id)

    if not file_obj:
        messages.error(request, "Erreur lors de l'upload.")
        return redirect(redirect_url)

    moderation_reason = services.moderation_message(services.get_user_by_id(user_id))
    if moderation_reason:
        messages.error(request, moderation_reason)
        return redirect(redirect_url)

    conv = services.get_conversation_for_user(conversation_id, user_id)
    if not conv:
        messages.error(request, 'Conversation invalide.')
        return redirect('index_php')

    try:
        file_meta = services.save_upload(file_obj)
        services.insert_message(user_id, conversation_id, f"a partage le fichier: {os.path.basename(file_obj.name)}", file_meta=file_meta)
        messages.success(request, 'Fichier uploade avec succes!')
    except Exception:
        messages.error(request, "Erreur lors de l'upload du fichier.")

    return redirect(redirect_url)


@require_GET
def download_view(request):
    if not require_login(request):
        return redirect('login_php')

    file_id = int(request.GET.get('id') or 0)
    if file_id <= 0:
        return HttpResponse('Fichier non specifie.', status=400)

    row = services.get_file_by_id(file_id)
    if not row:
        return HttpResponse('Fichier non trouve.', status=404)

    path = os.path.join(settings.MEDIA_ROOT, os.path.basename(row['filename']))
    if not os.path.isfile(path):
        return HttpResponse('Fichier non trouve sur le serveur.', status=404)

    response = FileResponse(open(path, 'rb'), as_attachment=True, filename=os.path.basename(row['original_name']))
    response['Content-Type'] = 'application/octet-stream'
    return response


@require_GET
def view_file_view(request):
    if not require_login(request):
        return HttpResponseForbidden('Acces interdit.')

    file_id = int(request.GET.get('id') or 0)
    if file_id <= 0:
        return HttpResponse('Fichier invalide.', status=400)

    row = services.get_file_by_id(file_id)
    if not row:
        return HttpResponse('Fichier introuvable.', status=404)

    path = os.path.join(settings.MEDIA_ROOT, os.path.basename(row['filename']))
    if not os.path.isfile(path):
        return HttpResponse('Fichier introuvable.', status=404)

    resp = FileResponse(open(path, 'rb'))
    resp['Content-Type'] = row.get('file_type') or 'application/octet-stream'
    resp['Content-Disposition'] = f'inline; filename="{os.path.basename(row["original_name"])}"'
    resp['Cache-Control'] = 'private, max-age=3600'
    return resp


@require_GET
def delete_file_view(request):
    if not require_login(request):
        return redirect('login_php')

    file_id = int(request.GET.get('id') or 0)
    if file_id <= 0:
        messages.error(request, 'Fichier non specifie.')
        return redirect('index_php')

    if services.delete_owned_file(file_id, int(request.session['user_id'])):
        messages.success(request, 'Fichier supprime avec succes.')
    else:
        messages.error(request, "Fichier non trouve ou vous n'avez pas la permission de le supprimer.")

    return redirect('index_php')


@require_http_methods(['GET', 'POST'])
def profile_view(request):
    if not require_login(request):
        return redirect('login_php')

    session_user_id = int(request.session['user_id'])
    requested_user_id = int(request.GET.get('user_id') or session_user_id)

    if requested_user_id != session_user_id and not services.is_admin_session(request):
        messages.error(request, 'Acces refuse a ce profil.')
        return redirect('profile_php')

    if request.method == 'POST' and request.POST.get('update_profile_picture') == '1':
        if requested_user_id != session_user_id:
            messages.error(request, 'Seul le proprietaire peut modifier sa photo de profil.')
            return redirect(f"{reverse('profile_php')}?user_id={requested_user_id}")

        file_obj = request.FILES.get('profile_picture')
        if file_obj:
            ok, err = services.update_profile_picture(session_user_id, file_obj)
            if ok:
                messages.success(request, 'Photo de profil mise a jour.')
            else:
                messages.error(request, err or 'Mise a jour impossible.')

        return redirect('profile_php')

    user = services.get_user_by_id(requested_user_id)
    if not user:
        messages.error(request, 'Profil utilisateur introuvable.')
        return redirect('index_php')

    stats, user_files = services.get_user_stats(requested_user_id)

    return render(
        request,
        'chat/profile.html',
        {
            'title': f"Profil - {user['username']}",
            'user': user,
            'stats': stats,
            'user_files': user_files,
            'is_own_profile': requested_user_id == session_user_id,
        },
    )


@require_http_methods(['GET', 'POST'])
def admin_view(request):
    if not require_login(request) or not services.is_admin_session(request):
        return redirect('index_php')

    current_admin_id = int(request.session['user_id'])
    current_is_super = services.is_user_super_admin(current_admin_id)

    filters = {
        'q': (request.GET.get('q') or '').strip(),
        'role': request.GET.get('role') or 'all',
        'status': request.GET.get('status') or 'all',
        'sort': request.GET.get('sort') or 'created_desc',
        'per_page': int(request.GET.get('per_page') or 12),
        'page': int(request.GET.get('page') or 1),
    }

    group_user_q = (request.GET.get('group_user_q') or '').strip()
    group_add_q = (request.GET.get('group_add_q') or '').strip()

    if not request.session.get('admin_csrf_token'):
        request.session['admin_csrf_token'] = secrets.token_hex(32)

    if request.method == 'POST':
        if request.POST.get('csrf_token') != request.session.get('admin_csrf_token'):
            messages.error(request, 'Session expiree. Veuillez reessayer.')
            return redirect('admin_php')

        action = request.POST.get('admin_action') or ''
        target_id = int(request.POST.get('user_id') or 0)

        try:
            if action == 'create_user':
                role = request.POST.get('create_role') or 'user'
                if role == 'admin' and not current_is_super:
                    raise ValueError('Seul le super admin peut creer un administrateur.')

                ok, err, created_id = services.create_user_by_admin(
                    request.POST.get('create_username') or '',
                    request.POST.get('create_password') or '',
                    request.POST.get('create_email') or '',
                    role,
                )
                if not ok:
                    raise ValueError(err)

                services.log_admin_action(
                    current_admin_id,
                    'CREATE_USER',
                    'user',
                    created_id,
                    f"Creation utilisateur: {request.POST.get('create_username')} ({role})",
                )
                messages.success(request, 'Utilisateur cree avec succes.')

            elif action == 'update_role':
                ok, err = services.update_user_role(current_admin_id, target_id, request.POST.get('role') or 'user')
                if not ok:
                    raise ValueError(err)

                services.log_admin_action(current_admin_id, 'UPDATE_ROLE', 'user', target_id, f"Role change en: {request.POST.get('role')}")
                messages.success(request, 'Role utilisateur mis a jour.')

            elif action in ('block_user', 'unblock_user', 'sanction_user', 'clear_sanction', 'reset_password', 'delete_user'):
                ok_perm, perm_err, _target = services.check_manage_target_permissions(current_admin_id, target_id, allow_self=False)
                if not ok_perm:
                    raise ValueError(perm_err)

                if action == 'block_user':
                    reason = (request.POST.get('reason') or '').strip() or 'Blocage administratif'
                    services.block_user(target_id, reason)
                    services.log_admin_action(current_admin_id, 'BLOCK_USER', 'user', target_id, reason)
                    messages.success(request, 'Utilisateur bloque.')

                elif action == 'unblock_user':
                    services.unblock_user(target_id)
                    services.log_admin_action(current_admin_id, 'UNBLOCK_USER', 'user', target_id, 'Deblocage utilisateur')
                    messages.success(request, 'Utilisateur debloque.')

                elif action == 'sanction_user':
                    hours = int(request.POST.get('duration_hours') or 24)
                    reason = (request.POST.get('reason') or '').strip() or 'Sanction administrative'
                    services.sanction_user(target_id, hours, reason)
                    services.log_admin_action(current_admin_id, 'SANCTION_USER', 'user', target_id, f'{reason} ({hours}h)')
                    messages.success(request, 'Sanction appliquee.')

                elif action == 'clear_sanction':
                    services.clear_sanction(target_id)
                    services.log_admin_action(current_admin_id, 'CLEAR_SANCTION', 'user', target_id, 'Sanction supprimee')
                    messages.success(request, 'Sanction supprimee.')

                elif action == 'reset_password':
                    ok, err = services.reset_password(target_id, request.POST.get('new_password') or '')
                    if not ok:
                        raise ValueError(err)
                    services.log_admin_action(current_admin_id, 'RESET_PASSWORD', 'user', target_id, 'Mot de passe reinitialise')
                    messages.success(request, 'Mot de passe reinitialise.')

                elif action == 'delete_user':
                    services.delete_user_with_assets(target_id)
                    services.log_admin_action(current_admin_id, 'DELETE_USER', 'user', target_id, 'Utilisateur supprime')
                    messages.success(request, 'Utilisateur supprime avec succes.')

            elif action == 'create_group':
                group_name = request.POST.get('group_name') or ''
                member_ids = request.POST.getlist('member_ids')
                ok, err, group_id = services.create_group_with_members(current_admin_id, group_name, member_ids)
                if not ok:
                    raise ValueError(err)

                services.log_admin_action(current_admin_id, 'CREATE_GROUP', 'conversation', group_id, f'Groupe cree: {group_name}')
                messages.success(request, 'Groupe cree avec succes.')

            elif action == 'add_group_members':
                group_id = int(request.POST.get('group_id') or 0)
                member_ids = request.POST.getlist('member_ids')
                ok, err = services.add_users_to_group(current_admin_id, group_id, member_ids)
                if not ok:
                    raise ValueError(err)

                services.log_admin_action(current_admin_id, 'ADD_GROUP_MEMBERS', 'conversation', group_id, f"Ajout membres: {', '.join(member_ids)}")
                messages.success(request, 'Utilisateurs ajoutes au groupe.')

        except ValueError as exc:
            messages.error(request, str(exc))

        return redirect('admin_php')

    users_data = services.get_users_for_admin(filters)
    context = {
        'title': 'Dashboard Admin',
        'stats': services.get_admin_stats(),
        'users': users_data['users'],
        'total_users_filtered': users_data['total'],
        'total_pages': users_data['total_pages'],
        'current_page': users_data['page'],
        'filters': filters,
        'logs': services.get_admin_logs(35),
        'admin_csrf_token': request.session.get('admin_csrf_token'),
        'current_is_super_admin': current_is_super,
        'group_user_q': group_user_q,
        'group_add_q': group_add_q,
        'group_create_candidates': services.search_users_for_group(group_user_q, 40),
        'group_add_candidates': services.search_users_for_group(group_add_q, 40),
        'groups': services.get_admin_group_overview(),
    }
    return render(request, 'chat/admin.html', context)
