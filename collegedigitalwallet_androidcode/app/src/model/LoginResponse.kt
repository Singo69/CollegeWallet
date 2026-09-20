package com.example.collegedigitalwallet.model

data class LoginResponse(
    val status: String,
    val message: String,
    val username: String?,
    val full_name: String?,
    val studentId: String?,   // ✅ must be studentId
    val program: String?,
    val balance: Double?
)


