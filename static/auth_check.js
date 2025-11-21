/**
 * 通用认证检查脚本
 * 在所有需要认证的页面中引入此脚本，确保用户已登录
 */

(function() {
    'use strict';
    
    // 检查当前页面是否是登录页面
    const isLoginPage = window.location.pathname.includes('login.html') || 
                        window.location.pathname === '/' && window.location.search.includes('login');
    
    // 如果不是登录页面，检查登录状态
    if (!isLoginPage) {
        const token = localStorage.getItem('access_token');
        
        if (!token) {
            // 没有token，重定向到登录页
            console.log('No authentication token found, redirecting to login page');
            // 保存当前URL，登录后可以返回
            const currentUrl = window.location.href;
            if (currentUrl && !currentUrl.includes('login.html')) {
                sessionStorage.setItem('redirect_after_login', currentUrl);
            }
            window.location.href = '/static/login.html';
            return;
        }
        
        // 验证token是否有效（可选：发送请求到服务器验证）
        // 这里只做基本检查，详细的验证在API调用时进行
        try {
            // 简单的token格式检查（JWT token通常包含三个部分，用.分隔）
            const tokenParts = token.split('.');
            if (tokenParts.length !== 3) {
                console.warn('Invalid token format, redirecting to login');
                localStorage.removeItem('access_token');
                window.location.href = '/static/login.html';
                return;
            }
        } catch (e) {
            console.error('Error checking token:', e);
            localStorage.removeItem('access_token');
            window.location.href = '/static/login.html';
            return;
        }
    }
    
    // 导出认证检查函数，供其他脚本使用
    window.checkAuth = function() {
        const token = localStorage.getItem('access_token');
        if (!token) {
            window.location.href = '/static/login.html';
            return false;
        }
        return true;
    };
    
    // 导出获取token的函数
    window.getAuthToken = function() {
        return localStorage.getItem('access_token');
    };
    
    // 导出登出函数
    window.logout = function() {
        localStorage.removeItem('access_token');
        window.location.href = '/static/login.html';
    };
})();

